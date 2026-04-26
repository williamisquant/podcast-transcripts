#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


def load_dotenv(project_root: Path) -> None:
    env_path = project_root / '.env'
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding='utf-8').splitlines():
        line = raw_line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def infer_show_config(show: str) -> dict[str, str]:
    prefix = show.upper()
    feed_url = os.environ.get(f'{prefix}_FEED_URL', '')
    show_slug = os.environ.get(f'{prefix}_SHOW_SLUG', show.lower())
    show_name = os.environ.get(f'{prefix}_SHOW_NAME', show)
    host = os.environ.get(f'{prefix}_HOST', '')
    return {
        'feed_url': feed_url,
        'show_slug': show_slug,
        'show_name': show_name,
        'host': host,
    }


def slugify(text: str, max_len: int = 80) -> str:
    text = text.strip().lower()
    text = text.replace('｜', '-').replace('|', '-')
    text = re.sub(r'\s+', '-', text)
    text = re.sub(r'[^\w\-\u4e00-\u9fff]+', '-', text)
    text = re.sub(r'-+', '-', text).strip('-_')
    return text[:max_len] or 'episode'


def read_episode_meta(project_root: Path, show_slug: str, episode_number: str) -> tuple[dict[str, Any], str]:
    episodes_dir = project_root / 'metadata' / 'episodes'
    candidates = sorted(episodes_dir.glob(f'{show_slug}-ep{episode_number}*-metadata.json'))
    if not candidates:
        raise FileNotFoundError(f'Cannot find metadata for episode {episode_number} under {episodes_dir}')
    path = candidates[0]
    data = json.loads(path.read_text(encoding='utf-8'))
    base = path.name.removesuffix('-metadata.json')
    return data, base


def maybe_run_transcribe(args: argparse.Namespace, project_root: Path, cfg: dict[str, str]) -> None:
    if args.skip_transcribe:
        return
    if not cfg['feed_url']:
        raise RuntimeError(f'Missing {args.show.upper()}_FEED_URL in .env or environment')
    cmd = [
        sys.executable,
        str(project_root / 'scripts' / 'transcribe_rss_feed.py'),
        '--feed-url',
        cfg['feed_url'],
        '--show-slug',
        cfg['show_slug'],
    ]
    if args.episode_number:
        cmd += ['--episode-number', args.episode_number]
    if args.title_contains:
        cmd += ['--title-contains', args.title_contains]
    if args.force:
        cmd.append('--force')
    subprocess.run(cmd, cwd=project_root, check=True)


def extract_uncertain_terms(clean_path: Path) -> list[dict[str, str]]:
    text = clean_path.read_text(encoding='utf-8')
    lines = [ln for ln in text.splitlines() if ln.startswith('[')]
    seen: set[tuple[str, str]] = set()
    items: list[dict[str, str]] = []

    suspicious_patterns = [
        r'[A-Z][A-Za-z0-9\-]{2,}',
        r'\b[A-Za-z]{3,}\b',
        r'\d+[A-Za-z]+',
    ]
    hard_terms = ['古愛', '聖夢公', '項目公', '全子股', '駕動率', '招的說法', '忍到', '畏介']

    for line in lines:
        m_ts = re.match(r'^\[([^\]]+)\]\s*(.*)$', line)
        if not m_ts:
            continue
        ts, content = m_ts.group(1), m_ts.group(2)
        found_terms: list[str] = []
        for term in hard_terms:
            if term in content:
                found_terms.append(term)
        for pat in suspicious_patterns:
            found_terms.extend(re.findall(pat, content))
        for term in found_terms:
            key = (ts, term)
            if key in seen:
                continue
            seen.add(key)
            candidate = '待確認'
            note = '自動偵測到的可疑詞，建議回聽複核。'
            if term in ('古愛',):
                candidate = '股癌'
                note = '節目名高機率誤辨。'
            elif term in ('聖夢公', '項目公'):
                candidate = '謝孟恭'
                note = '主持人姓名高機率誤辨。'
            elif term == '全子股':
                candidate = '權值股'
                note = '股市語境常見 ASR 誤辨。'
            elif term == '駕動率':
                candidate = '稼動率'
                note = '產業語境常見誤辨。'
            items.append({
                'timestamp': ts,
                'term': term,
                'candidate': candidate,
                'note': note,
                'excerpt': line,
                'status': 'needs_review',
            })
            if len(items) >= 12:
                return items
    return items


def main() -> int:
    parser = argparse.ArgumentParser(description='Unified episode processing wrapper for podcast-transcripts.')
    parser.add_argument('--show', default='gooaye')
    parser.add_argument('--episode-number', required=True)
    parser.add_argument('--title-contains')
    parser.add_argument('--project-root', default=os.environ.get('PODCAST_PROJECT_ROOT', '.'))
    parser.add_argument('--skip-transcribe', action='store_true')
    parser.add_argument('--force', action='store_true')
    parser.add_argument('--overwrite-artifacts', action='store_true')
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    load_dotenv(project_root)
    cfg = infer_show_config(args.show)
    maybe_run_transcribe(args, project_root, cfg)

    meta, base = read_episode_meta(project_root, cfg['show_slug'], args.episode_number)
    clean_path = project_root / 'transcripts' / 'clean' / f'{base}-transcript.md'
    if not clean_path.exists():
        raise FileNotFoundError(f'Missing clean transcript: {clean_path}')

    reviews_dir = project_root / 'metadata' / 'reviews'
    summaries_dir = project_root / 'summaries'
    reviews_dir.mkdir(parents=True, exist_ok=True)
    summaries_dir.mkdir(parents=True, exist_ok=True)

    uncertain = extract_uncertain_terms(clean_path)
    uncertain_path = reviews_dir / f'{base}-uncertain-terms.json'
    if args.overwrite_artifacts or not uncertain_path.exists():
        uncertain_path.write_text(json.dumps(uncertain, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    summary_path = summaries_dir / f'{base}-summary.md'

    print(json.dumps({
        'base': base,
        'episode_metadata': str((project_root / 'metadata' / 'episodes' / f'{base}-metadata.json')),
        'clean_transcript': str(clean_path),
        'uncertain_terms': str(uncertain_path),
        'summary_target': str(summary_path),
        'uncertain_count': len(uncertain),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
