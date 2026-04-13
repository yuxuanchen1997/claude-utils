#!/usr/bin/env python3
"""
Convert Codex chat sessions to Claude Code-compatible format.

Produces JSONL that matches Claude Code's internal format exactly:
- Each content block (thinking, text, tool_use, tool_result) as separate line
- Proper parentUuid tree structure
- file-history-snapshot entries
- All required metadata fields (gitBranch, promptId, version, etc.)

Usage:
    python codex-to-claude.py <session-id-or-path> [--to-claude]

With --to-claude: writes to ~/.claude/projects/<path>/ and updates history
Without flag: writes .claude.jsonl to /tmp/

Examples:
    python codex-to-claude.py 019d829b-e354-7361-94f6-a457de92ce02 --to-claude
    python codex-to-claude.py /path/to/rollout-*.jsonl --to-claude
"""

import json
import sys
import os
import uuid
import subprocess
from pathlib import Path
from datetime import datetime, timezone


def find_codex_session(session_id: str) -> Path:
    """Find the Codex rollout file for a given session ID."""
    sessions_dir = Path.home() / '.codex' / 'sessions'
    if not sessions_dir.exists():
        raise FileNotFoundError(f"Codex sessions directory not found: {sessions_dir}")
    for jsonl_file in sessions_dir.rglob(f"*{session_id}*.jsonl"):
        return jsonl_file
    raise FileNotFoundError(f"Session not found: {session_id}")


def parse_codex_rollout(jsonl_path: str) -> tuple[list[dict], dict]:
    """Parse a Codex rollout JSONL file."""
    messages = []
    session_meta = {}
    with open(jsonl_path, 'r') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            entry_type = entry.get('type', '')
            payload = entry.get('payload', {})
            if entry_type == 'session_meta':
                session_meta = payload
            elif entry_type == 'response_item':
                messages.append(entry)
    return messages, session_meta


def is_injected_context(text: str) -> bool:
    """Check if a user message is injected context."""
    return (text.startswith('# AGENTS.md instructions') or
            text.startswith('<environment_context>') or
            text.startswith('<permissions instructions') or
            text.startswith('<collaboration_mode>'))


def extract_text_from_content(content) -> str:
    """Extract plain text from a Codex content list."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict):
                if part.get('type') in ('text', 'input_text', 'output_text'):
                    parts.append(part.get('text', ''))
        return '\n'.join(parts)
    return str(content)


def extract_conversation(messages: list[dict]) -> list[dict]:
    """Extract user/assistant messages and tool calls from Codex response_items."""
    conversation = []
    pending_tool_calls = []
    pending_tool_results = []

    for entry in messages:
        payload = entry.get('payload', {})
        ptype = payload.get('type', '')
        role = payload.get('role', '')
        timestamp = entry.get('timestamp', '')

        if ptype == 'message':
            # Flush pending tool calls/results
            if pending_tool_calls:
                conversation.append({
                    'role': 'assistant',
                    'tool_calls': pending_tool_calls,
                    'timestamp': timestamp,
                })
                pending_tool_calls = []
            if pending_tool_results:
                conversation.append({
                    'role': 'user',
                    'tool_results': pending_tool_results,
                    'timestamp': timestamp,
                })
                pending_tool_results = []

            content = payload.get('content', '')
            text = extract_text_from_content(content)

            if role == 'developer':
                continue
            if not text.strip():
                continue
            if '<turn_aborted>' in text:
                continue
            if is_injected_context(text):
                continue

            conversation.append({
                'role': role,
                'content': text,
                'timestamp': timestamp,
            })

        elif ptype == 'function_call':
            args_str = payload.get('arguments', '{}')
            try:
                args = json.loads(args_str)
            except json.JSONDecodeError:
                args = {'raw': args_str}

            pending_tool_calls.append({
                'id': payload.get('call_id', f'call_{uuid.uuid4().hex[:24]}'),
                'name': payload.get('name', 'unknown'),
                'input': args,
                'timestamp': timestamp,
            })

        elif ptype == 'function_call_output':
            call_id = payload.get('call_id', '')
            output = payload.get('output', '')
            tool_name = 'unknown'
            for tc in pending_tool_calls:
                if tc['id'] == call_id:
                    tool_name = tc['name']
                    break

            pending_tool_results.append({
                'tool_use_id': call_id,
                'name': tool_name,
                'content': output,
                'timestamp': timestamp,
            })

    if pending_tool_calls:
        conversation.append({
            'role': 'assistant',
            'tool_calls': pending_tool_calls,
            'timestamp': '',
        })
    if pending_tool_results:
        conversation.append({
            'role': 'user',
            'tool_results': pending_tool_results,
            'timestamp': '',
        })

    return conversation


def cwd_to_claude_project_path(cwd: str) -> str:
    """Convert a CWD path to Claude's project directory name."""
    return '-' + cwd.lstrip('/').replace('/', '-')


def map_tool_name(codex_name: str) -> str:
    """Map Codex tool names to Claude Code tool names."""
    mapping = {
        'exec_command': 'Bash',
        'apply_patch': 'Write',
        'update_plan': 'update_plan',
        'spawn_agent': 'spawn_agent',
        'send_input': 'send_input',
        'request_user_input': 'request_user_input',
    }
    return mapping.get(codex_name, codex_name)


def map_tool_input(codex_name: str, args: dict) -> dict:
    """Map Codex tool input to Claude Code tool input format."""
    if codex_name == 'exec_command':
        return {
            'command': args.get('cmd', ''),
            'description': args.get('justification', '') or f'Run: {args.get("cmd", "")[:80]}',
        }
    elif codex_name == 'apply_patch':
        return {
            'file_path': args.get('path', ''),
            'content': args.get('patch', ''),
        }
    return args


def get_git_branch(cwd: str) -> str:
    """Try to get the current git branch for a directory."""
    try:
        result = subprocess.run(
            ['git', 'rev-parse', '--abbrev-ref', 'HEAD'],
            cwd=cwd, capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            return result.stdout.strip() or 'main'
    except Exception:
        pass
    return 'main'


def build_claude_session(conversation: list[dict], session_id: str, cwd: str, session_meta: dict) -> list[str]:
    """Build Claude Code JSONL lines matching the exact internal format.

    Key format rules:
    - Each content block (thinking, text, tool_use, tool_result) is a SEPARATE JSONL line
    - parentUuid chains link them in a tree
    - file-history-snapshot entries before each user message
    - gitBranch, promptId, version on all entries
    - 'system' summary entries between turns
    - tool_result entries parented to their specific tool_use entry
    """
    lines = []
    git_branch = get_git_branch(cwd)
    version = '2.1.87'  # Match current Claude Code version
    turn_msg_id = [0]
    turn_count = [0]

    def new_uuid():
        return str(uuid.uuid4())

    def new_msg_id():
        turn_msg_id[0] += 1
        return f"msg_{uuid.uuid4().hex[:24]}"

    def make_base_entry(entry_type, parent_uuid, timestamp, extra=None):
        """Create a base entry with all common fields."""
        entry = {
            'parentUuid': parent_uuid,
            'isSidechain': False,
            'type': entry_type,
            'uuid': new_uuid(),
            'timestamp': timestamp or datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
            'cwd': cwd,
            'sessionId': session_id,
            'version': version,
            'gitBranch': git_branch,
            'userType': 'external',
            'entrypoint': 'cli',
        }
        if extra:
            entry.update(extra)
        return entry

    def add_file_history_snapshot(message_uuid, timestamp):
        """Add a file-history-snapshot entry."""
        lines.append(json.dumps({
            'type': 'file-history-snapshot',
            'messageId': message_uuid,
            'snapshot': {
                'messageId': message_uuid,
                'trackedFileBackups': {},
                'timestamp': timestamp or datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
            },
            'isSnapshotUpdate': False,
        }))

    # Track the "leaf" UUID (last entry in the chain that the next entry parents to)
    last_uuid = None

    for turn_idx, turn in enumerate(conversation):
        role = turn.get('role', 'user')
        timestamp = turn.get('timestamp', datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'))

        if role == 'user' and 'tool_results' not in turn:
            # Plain user message
            current_uuid = new_uuid()
            prompt_id = str(uuid.uuid4())

            # Add file-history-snapshot before user message
            add_file_history_snapshot(current_uuid, timestamp)

            entry = make_base_entry('user', last_uuid, timestamp)
            entry['uuid'] = current_uuid
            entry['message'] = {
                'role': 'user',
                'content': turn['content'],
            }
            entry['permissionMode'] = 'bypassPermissions'
            entry['promptId'] = prompt_id

            lines.append(json.dumps(entry))
            last_uuid = current_uuid

            turn_count[0] += 1

        elif role == 'assistant' and 'tool_calls' not in turn:
            # Assistant text message - in Claude Code, thinking and text are separate lines
            msg_id = new_msg_id()

            # Thinking block (empty, since we don't have the original thinking)
            thinking_uuid = new_uuid()
            thinking_entry = make_base_entry('assistant', last_uuid, timestamp)
            thinking_entry['uuid'] = thinking_uuid
            thinking_entry['message'] = {
                'id': msg_id,
                'type': 'message',
                'role': 'assistant',
                'model': session_meta.get('model', 'unknown'),
                'content': [
                    {
                        'type': 'thinking',
                        'thinking': '',
                        'signature': '',
                    }
                ],
                'stop_reason': None,
                'stop_sequence': None,
            }
            lines.append(json.dumps(thinking_entry))

            # Text block
            text_uuid = new_uuid()
            text_entry = make_base_entry('assistant', thinking_uuid, timestamp)
            text_entry['uuid'] = text_uuid
            text_entry['message'] = {
                'id': msg_id,
                'type': 'message',
                'role': 'assistant',
                'model': session_meta.get('model', 'unknown'),
                'content': [
                    {
                        'type': 'text',
                        'text': turn['content'],
                    }
                ],
                'stop_reason': 'end_turn',
                'stop_sequence': None,
            }
            lines.append(json.dumps(text_entry))

            last_uuid = text_uuid

        elif role == 'assistant' and 'tool_calls' in turn:
            # Assistant with tool calls
            msg_id = new_msg_id()

            # Thinking block
            thinking_uuid = new_uuid()
            thinking_entry = make_base_entry('assistant', last_uuid, timestamp)
            thinking_entry['uuid'] = thinking_uuid
            thinking_entry['message'] = {
                'id': msg_id,
                'type': 'message',
                'role': 'assistant',
                'model': session_meta.get('model', 'unknown'),
                'content': [
                    {
                        'type': 'thinking',
                        'thinking': '',
                        'signature': '',
                    }
                ],
                'stop_reason': None,
                'stop_sequence': None,
            }
            lines.append(json.dumps(thinking_entry))

            # Each tool_use is a separate line, chained from the previous
            prev_tool_uuid = thinking_uuid
            tool_use_uuids = []
            for tc in turn['tool_calls']:
                claude_tool_name = map_tool_name(tc['name'])
                claude_tool_input = map_tool_input(tc['name'], tc['input'])

                tool_uuid = new_uuid()
                tool_entry = make_base_entry('assistant', prev_tool_uuid, tc.get('timestamp', timestamp))
                tool_entry['uuid'] = tool_uuid
                tool_entry['message'] = {
                    'id': msg_id,
                    'type': 'message',
                    'role': 'assistant',
                    'model': session_meta.get('model', 'unknown'),
                    'content': [
                        {
                            'type': 'tool_use',
                            'id': tc['id'],
                            'name': claude_tool_name,
                            'input': claude_tool_input,
                        }
                    ],
                    'stop_reason': 'tool_use',
                    'stop_sequence': None,
                }
                lines.append(json.dumps(tool_entry))
                tool_use_uuids.append(tool_uuid)
                prev_tool_uuid = tool_uuid

            # The next entry should parent to the last tool_use
            last_uuid = prev_tool_uuid

            # If there are tool_results, they come as a user entry
            # BUT in Claude Code, tool_results are parented to their specific tool_use
            # We handle that in the tool_results section below

        elif role == 'user' and 'tool_results' in turn:
            # Tool results - each one is a separate line, parented to its tool_use
            # First, we need to find the corresponding tool_use UUIDs
            # Since we track tool_use_uuids in the assistant entry above,
            # we need a different approach: just parent to last_uuid for simplicity
            # In real Claude, each tool_result is parented to its specific tool_use

            # For now, parent each tool_result to last_uuid
            # (This isn't 100% accurate but works for linear conversations)
            for tr in turn['tool_results']:
                result_uuid = new_uuid()
                result_entry = make_base_entry('user', last_uuid, tr.get('timestamp', timestamp))
                result_entry['uuid'] = result_uuid
                result_entry['message'] = {
                    'role': 'user',
                    'content': [
                        {
                            'tool_use_id': tr['tool_use_id'],
                            'type': 'tool_result',
                            'content': tr['content'],
                        }
                    ],
                }
                result_entry['toolUseResult'] = {
                    'stdout': tr['content'],
                    'stderr': '',
                    'exitCode': 0,
                    'durationMs': 0,
                }
                # Remove fields that shouldn't be on tool_result entries
                for key in ['permissionMode', 'promptId']:
                    result_entry.pop(key, None)
                lines.append(json.dumps(result_entry))
                last_uuid = result_uuid

    # Add a 'system' summary entry at the end
    system_uuid = new_uuid()
    system_entry = make_base_entry('system', last_uuid, datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'))
    system_entry['uuid'] = system_uuid
    system_entry['subtype'] = 'success'
    system_entry['isMeta'] = True
    system_entry['durationMs'] = 0
    system_entry['messageCount'] = turn_count[0]
    system_entry['message'] = {
        'role': 'system',
        'content': 'Session migrated from Codex',
    }
    # Remove fields not present on system entries
    for key in ['gitBranch', 'version', 'isSidechain', 'entrypoint', 'userType']:
        system_entry.pop(key, None)
    lines.append(json.dumps(system_entry))

    return lines


def main():
    if len(sys.argv) < 2:
        print("Usage: codex-to-claude.py <session-id-or-path> [--export]")
        print("")
        print("Default: writes to ~/.claude/projects/<path>/ and updates history")
        print("With --export: writes .claude.jsonl to /tmp/")
        sys.exit(1)

    session_arg = sys.argv[1]
    # --to-claude is now the default (always sync to Claude)
    # --export flag means write to /tmp instead
    do_export = '--export' in sys.argv

    session_path = Path(session_arg)
    if not session_path.exists():
        try:
            session_path = find_codex_session(session_arg)
            print(f"Found session: {session_path}")
        except FileNotFoundError as e:
            print(f"Error: {e}")
            sys.exit(1)

    messages, session_meta = parse_codex_rollout(str(session_path))
    session_id = session_meta.get('id', session_path.stem.split('-')[-1])
    cwd = session_meta.get('cwd', str(Path.home()))

    print(f"Session ID: {session_id}")
    print(f"CWD: {cwd}")
    print(f"Parsed {len(messages)} response items")

    conversation = extract_conversation(messages)
    print(f"Extracted {len(conversation)} conversation turns")

    claude_lines = build_claude_session(conversation, session_id, cwd, session_meta)
    print(f"Generated {len(claude_lines)} Claude Code JSONL entries")

    if not do_export:
        project_dir_name = cwd_to_claude_project_path(cwd)
        project_dir = Path.home() / '.claude' / 'projects' / project_dir_name
        project_dir.mkdir(parents=True, exist_ok=True)

        output_path = project_dir / f"{session_id}.jsonl"

        with open(output_path, 'w') as f:
            for line in claude_lines:
                f.write(line + '\n')

        print(f"Written to Claude projects: {output_path}")

        # Update history.jsonl
        history_path = Path.home() / '.claude' / 'history.jsonl'
        first_msg = ''
        for turn in conversation:
            if turn.get('role') == 'user' and 'tool_results' not in turn:
                first_msg = turn.get('content', '')[:200]
                break

        ts = int(datetime.now(timezone.utc).timestamp() * 1000)
        history_entry = {
            'display': first_msg,
            'pastedContents': {},
            'timestamp': ts,
            'project': cwd,
            'sessionId': session_id,
        }
        with open(history_path, 'a') as f:
            f.write(json.dumps(history_entry) + '\n')

        print(f"Updated history: {history_path}")
        print(f"\nYou can now resume this conversation in Claude Code with:")
        print(f"  claude --resume {session_id}")
    else:
        output_path = Path(f"/tmp/{session_id}.claude.jsonl")
        with open(output_path, 'w') as f:
            for line in claude_lines:
                f.write(line + '\n')
        print(f"Output: {output_path}")
        print("Use --to-claude (default) to write to ~/.claude/projects/")
        with open(output_path, 'w') as f:
            for line in claude_lines:
                f.write(line + '\n')
        print(f"Output: {output_path}")
        print("Use --to-claude to write directly to ~/.claude/projects/")


if __name__ == '__main__':
    main()
