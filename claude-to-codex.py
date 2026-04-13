#!/usr/bin/env python3
"""
Convert Claude Code chat sessions to Codex-compatible format.

Usage:
    python claude-to-codex.py <session-id> [--to-codex]

With --to-codex: writes to ~/.codex/sessions/ (or /tmp if read-only)
Without flag: writes .codex.jsonl to /tmp/

Example:
    python claude-to-codex.py cda34e6c-89b7-41f9-8c86-6edfbab6d446 --to-codex
"""

import json
import sys
import os
import uuid
from pathlib import Path
from datetime import datetime, timezone


def parse_claude_session(jsonl_path: str) -> list[dict]:
    messages = []
    with open(jsonl_path, 'r') as f:
        for line in f:
            line = line.strip()
            if not line: continue
            try:
                msg = json.loads(line)
                if msg.get('type') == 'file-history-snapshot': continue
                if msg.get('type') == 'last-prompt': continue
                messages.append(msg)
            except json.JSONDecodeError: continue
    return messages


def get_message_content(msg: dict) -> str:
    message_data = msg.get('message', {})
    content = message_data.get('content', [])
    if isinstance(content, str): return content
    if isinstance(content, list):
        text_parts = []
        for part in content:
            if isinstance(part, dict):
                if part.get('type') == 'text':
                    text_parts.append(part.get('text', ''))
                elif part.get('type') == 'thinking':
                    pass
        return '\n'.join(text_parts)
    return str(content)


def is_tool_result(msg: dict) -> bool:
    return bool(msg.get('toolUseResult'))


def build_conversation(messages: list[dict]) -> list[dict]:
    roots = [msg for msg in messages if msg.get('parentUuid') is None and msg.get('uuid')]
    results = []
    def collect(msg):
        nonlocal results
        msg_type = msg.get('type')
        role = msg.get('message', {}).get('role', 'user')
        if msg_type == 'user' or role == 'user':
            if not is_tool_result(msg):
                content = get_message_content(msg)
                if content:
                    results.append({'role': 'user', 'content': content, 'uuid': msg.get('uuid'), 'timestamp': msg.get('timestamp')})
        elif msg_type == 'assistant' or role == 'assistant':
            content = get_message_content(msg)
            if content:
                results.append({'role': 'assistant', 'content': content, 'uuid': msg.get('uuid'), 'timestamp': msg.get('timestamp')})
        for m in messages:
            if m.get('parentUuid') == msg.get('uuid'):
                collect(m)
    for root in roots:
        collect(root)
    return results


def convert_to_codex_rollout(conversation: list[dict], session_id: str, cwd: str) -> list[dict]:
    lines = []
    now = datetime.now(timezone.utc)
    base_timestamp = now.isoformat().replace('+00:00', 'Z')
    session_timestamp = conversation[0]['timestamp'] if conversation else base_timestamp
    turn_id = str(uuid.uuid4())

    lines.append({'timestamp': base_timestamp, 'type': 'session_meta', 'payload': {'id': session_id, 'timestamp': session_timestamp, 'cwd': cwd, 'originator': 'codex-tui', 'cli_version': '0.120.0', 'source': 'cli', 'model_provider': 'converted', 'base_instructions': {'text': 'You are a helpful coding assistant.'}, 'git': None}})
    lines.append({'timestamp': base_timestamp, 'type': 'event_msg', 'payload': {'type': 'task_started', 'turn_id': turn_id, 'started_at': 0, 'model_context_window': 258400, 'collaboration_mode_kind': 'default'}})

    for msg in conversation:
        role = msg.get('role', 'user')
        content = msg.get('content', '')
        ts = msg.get('timestamp', base_timestamp)
        if role == 'user':
            lines.append({'timestamp': ts, 'type': 'response_item', 'payload': {'type': 'message', 'role': 'user', 'content': [{'type': 'input_text', 'text': content}]}})
            lines.append({'timestamp': ts, 'type': 'event_msg', 'payload': {'type': 'user_message', 'message': content, 'images': [], 'local_images': [], 'text_elements': []}})
        else:
            lines.append({'timestamp': ts, 'type': 'response_item', 'payload': {'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text', 'text': content}]}})
            lines.append({'timestamp': ts, 'type': 'event_msg', 'payload': {'type': 'agent_message', 'message': content, 'phase': None, 'memory_citation': None}})

    lines.append({'timestamp': base_timestamp, 'type': 'event_msg', 'payload': {'type': 'task_complete', 'turn_id': turn_id, 'last_agent_message': conversation[-1]['content'] if conversation else '', 'completed_at': 0, 'duration_ms': 0}})
    return lines


def find_session_file(session_id: str) -> Path:
    claude_dir = Path.home() / '.claude' / 'projects'
    if not claude_dir.exists():
        raise FileNotFoundError(f"Claude projects directory not found: {claude_dir}")
    for jsonl_file in claude_dir.rglob(f"{session_id}.jsonl"):
        return jsonl_file
    raise FileNotFoundError(f"Session not found: {session_id}")


def get_cwd_from_session(messages: list[dict]) -> str:
    for msg in messages:
        if msg.get('cwd'):
            return msg['cwd']
    return str(Path.home())


def main():
    if len(sys.argv) < 2:
        print("Usage: claude-to-codex.py <session-id> [--export]")
        sys.exit(1)

    session_id = sys.argv[1]
    do_export = '--export' in sys.argv  # --export means write to /tmp instead of syncing

    try:
        session_path = find_session_file(session_id)
        print(f"Found session: {session_path}")
    except FileNotFoundError as e:
        print(f"Error: {e}")
        sys.exit(1)

    messages = parse_claude_session(str(session_path))
    print(f"Parsed {len(messages)} messages")

    conversation = build_conversation(messages)
    print(f"Built conversation with {len(conversation)} messages")

    cwd = get_cwd_from_session(messages)

    if not do_export:
        rollout_lines = convert_to_codex_rollout(conversation, session_id, cwd)

        # Try ~/.codex/sessions first, fall back to /tmp
        if conversation:
            try:
                ts = datetime.fromisoformat(conversation[0]['timestamp'].replace('Z', '+00:00'))
            except:
                ts = datetime.now(timezone.utc)
            year, month, day = ts.strftime('%Y'), ts.strftime('%m'), ts.strftime('%d')
            session_timestamp = conversation[0]['timestamp'][:19] if conversation else ts.isoformat()
            time_str = session_timestamp[11:19].replace(':', '-')
            rollout_filename = f"rollout-{year}-{month}-{day}T{time_str}-{session_id}.jsonl"

            codex_dir = Path.home() / '.codex' / 'sessions' / year / month / day
            try:
                codex_dir.mkdir(parents=True, exist_ok=True)
                output_path = codex_dir / rollout_filename

                with open(output_path, 'w') as f:
                    for line in rollout_lines:
                        f.write(json.dumps(line) + '\n')
                print(f"Written to Codex sessions: {output_path}")

                # Update history
                history_path = Path.home() / '.codex' / 'history.jsonl'
                first_msg_preview = conversation[0]['content'][:100] if conversation else ''
                history_entry = {'session_id': session_id, 'ts': int(datetime.now(timezone.utc).timestamp()), 'text': first_msg_preview}
                with open(history_path, 'a') as f:
                    f.write(json.dumps(history_entry) + '\n')
                print(f"Updated history: {history_path}")
            except OSError as e:
                # Fallback to /tmp
                output_path = Path(f"/tmp/{session_id}.codex.jsonl")
                with open(output_path, 'w') as f:
                    for line in rollout_lines:
                        f.write(json.dumps(line) + '\n')
                print(f"Codex sessions dir not writable, wrote to: {output_path}")
        else:
            print("No conversation to convert")
    else:
        output_path = Path(f"/tmp/{session_id}.codex.jsonl")
        rollout_lines = convert_to_codex_rollout(conversation, session_id, cwd)
        with open(output_path, 'w') as f:
            for line in rollout_lines:
                f.write(json.dumps(line) + '\n')
        print(f"Output: {output_path}")
        print("Use --to-codex (default) to write to ~/.codex/sessions/")


if __name__ == '__main__':
    main()
