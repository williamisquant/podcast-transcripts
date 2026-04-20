#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

from opencc import OpenCC

NS = {
    'itunes': 'http://www.itunes.com/dtds/podcast-1.0.dtd',
    'content': 'http://purl.org/rss/1.0/modules/content/',
    'dc': 'http://purl.org/dc/elements/1.1/',
}

CC_S2T = OpenCC('s2t')


def text_or_empty(value: str | None) -> str:
    return (value or '').strip()


def strip_tags(text: str) -> str:
    text = re.sub(r'<br\s*/?>', '\n', text, flags=re.I)
    text = re.sub(r'</p\s*>', '\n', text, flags=re.I)
    text = re.sub(r'<[^>]+>', '', text)
    return html.unescape(text).strip()


def slugify(text: str, max_len: int = 80) -> str:
    text = text.strip().lower()
    text = text.replace('｜', '-').replace('|', '-')
    text = re.sub(r'\s+', '-', text)
    text = re.sub(r'[^\w\-\u4e00-\u9fff]+', '-', text)
    text = re.sub(r'-+', '-', text).strip('-_')
    return text[:max_len] or 'episode'


def parse_feed(feed_url: str) -> dict[str, Any]:
    req = urllib.request.Request(feed_url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req) as resp:
        xml_bytes = resp.read()
    root = ET.fromstring(xml_bytes)
    channel = root.find('channel')
    if channel is None:
        raise RuntimeError('RSS feed missing channel element')

    channel_title = text_or_empty(channel.findtext('title'))
    channel_author = text_or_empty(channel.findtext('itunes:author', namespaces=NS))
    channel_desc = strip_tags(text_or_empty(channel.findtext('description')))
    items = []
    for item in channel.findall('item'):
        enclosure = item.find('enclosure')
        enc_url = enclosure.attrib.get('url', '').strip() if enclosure is not None else ''
        if not enc_url:
            continue
        title = text_or_empty(item.findtext('title'))
        guid = text_or_empty(item.findtext('guid')) or enc_url
        link = text_or_empty(item.findtext('link'))
        description = strip_tags(text_or_empty(item.findtext('description')))
        creator = text_or_empty(item.findtext('dc:creator', namespaces=NS)) or channel_author
        pub_date_raw = text_or_empty(item.findtext('pubDate'))
        pub_date_iso = ''
        if pub_date_raw:
            try:
                pub_dt = parsedate_to_datetime(pub_date_raw)
                if pub_dt.tzinfo is None:
                    pub_dt = pub_dt.replace(tzinfo=timezone.utc)
                pub_date_iso = pub_dt.astimezone(timezone.utc).date().isoformat()
            except Exception:
                pub_date_iso = pub_date_raw
        duration = text_or_empty(item.findtext('itunes:duration', namespaces=NS))
        episode_num = text_or_empty(item.findtext('itunes:episode', namespaces=NS))
        items.append({
            'title': title,
            'guid': guid,
            'link': link,
            'description': description,
            'creator': creator,
            'pub_date': pub_date_iso,
            'pub_date_raw': pub_date_raw,
            'duration': duration,
            'episode_number': episode_num,
            'audio_url': enc_url,
        })

    return {
        'show_title': channel_title,
        'show_author': channel_author,
        'show_description': channel_desc,
        'items': items,
    }


def download_file(url: str, dest: Path) -> None:
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req) as src, open(dest, 'wb') as out:
        shutil.copyfileobj(src, out)


def run_whisper(audio_path: Path, out_dir: Path, language: str, model: str, quiet: bool = True) -> Path:
    cmd = [
        'uvx', '--python', '3.11', '--from', 'openai-whisper', 'whisper',
        str(audio_path),
        '--model', model,
        '--language', language,
        '--output_format', 'json',
        '--output_dir', str(out_dir),
    ]
    kwargs = {}
    if quiet:
        kwargs = {'stdout': subprocess.DEVNULL, 'stderr': subprocess.DEVNULL}
    subprocess.run(cmd, check=True, **kwargs)
    return out_dir / f'{audio_path.stem}.json'


def select_items(feed_items: list[dict[str, Any]], args: argparse.Namespace) -> list[dict[str, Any]]:
    items = feed_items
    if args.episode_number:
        items = [item for item in items if str(item.get('episode_number') or '').strip() == str(args.episode_number).strip()]
    if args.title_contains:
        needle = args.title_contains.lower()
        items = [item for item in items if needle in item.get('title', '').lower()]
    if not args.episode_number and not args.title_contains:
        items = items[: args.limit]
    return items


def duration_to_seconds(value: str) -> int | None:
    if not value:
        return None
    parts = value.split(':')
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        return None
    if len(nums) == 3:
        h, m, s = nums
        return h * 3600 + m * 60 + s
    if len(nums) == 2:
        m, s = nums
        return m * 60 + s
    if len(nums) == 1:
        return nums[0]
    return None


def seconds_to_hms(seconds: int | None) -> str:
    if seconds is None:
        return ''
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f'{h:02d}:{m:02d}:{s:02d}'


def to_traditional_text(text: str) -> str:
    return CC_S2T.convert(text)


def write_clean_markdown(target: Path, meta: dict[str, Any], transcript_data: dict[str, Any]) -> None:
    lines: list[str] = []
    lines.append(f"# {meta['show']} {meta['episode_title']} 逐字稿")
    lines.append('')
    lines.append(f"- 主持人：{meta['host']}")
    if meta.get('episode_number'):
        lines.append(f"- 集數編號：{meta['episode_number']}")
    lines.append(f"- 標題：{meta['episode_title']}")
    if meta.get('published_date'):
        lines.append(f"- 日期：{meta['published_date']}")
    if meta.get('duration_hms'):
        lines.append(f"- 長度：{meta['duration_hms']}")
    lines.append(f"- 來源：{meta['transcript_source']}")
    if meta['source_urls'].get('episode_page'):
        lines.append(f"- 節目頁：{meta['source_urls']['episode_page']}")
    lines.append('')
    lines.append('> 註：此逐字稿為 ASR 自動辨識，可能有專有名詞、口語詞、數字或中英夾雜辨識誤差。')
    lines.append('')
    lines.append('## 全文')
    lines.append('')
    for seg in transcript_data.get('segments', []):
        start = int(seg['start'])
        hh, rem = divmod(start, 3600)
        mm, ss = divmod(rem, 60)
        text = ' '.join(str(seg['text']).split())
        text = to_traditional_text(text)
        lines.append(f'[{hh:02d}:{mm:02d}:{ss:02d}] {text}')
    target.write_text('\n'.join(lines), encoding='utf-8')


def process_episode(item: dict[str, Any], feed_meta: dict[str, Any], args: argparse.Namespace, project_root: Path) -> dict[str, Any]:
    raw_dir = project_root / 'transcripts' / 'raw'
    clean_dir = project_root / 'transcripts' / 'clean'
    meta_dir = project_root / 'metadata' / 'episodes'
    audio_dir = project_root / 'audio' if args.keep_audio else None
    for d in [raw_dir, clean_dir, meta_dir]:
        d.mkdir(parents=True, exist_ok=True)
    if audio_dir:
        audio_dir.mkdir(parents=True, exist_ok=True)

    title_slug = slugify(item['title'])
    show_slug = args.show_slug
    base = f'{show_slug}-{title_slug}'
    raw_target = raw_dir / f'{base}-whisper.json'
    clean_target = clean_dir / f'{base}-transcript.md'
    meta_target = meta_dir / f'{base}-metadata.json'

    if raw_target.exists() and clean_target.exists() and meta_target.exists() and not args.force:
        return {'status': 'skipped', 'title': item['title'], 'base': base}

    with tempfile.TemporaryDirectory(prefix=f'{base}-') as tmpdir:
        tmp = Path(tmpdir)
        audio_path = tmp / 'audio.mp3'
        download_file(item['audio_url'], audio_path)
        whisper_json = run_whisper(audio_path, tmp, args.language, args.model, quiet=not args.verbose_whisper)
        transcript_data = json.loads(whisper_json.read_text(encoding='utf-8'))
        raw_target.write_text(json.dumps(transcript_data, ensure_ascii=False, indent=2), encoding='utf-8')

        duration_seconds = duration_to_seconds(item['duration'])
        if duration_seconds is None:
            segs = transcript_data.get('segments', [])
            if segs:
                duration_seconds = int(segs[-1].get('end', 0))

        metadata = {
            'show': feed_meta['show_title'],
            'host': item['creator'] or feed_meta['show_author'],
            'episode_title': item['title'],
            'episode_number': item.get('episode_number') or None,
            'published_date': item.get('pub_date') or None,
            'duration_seconds': duration_seconds,
            'duration_hms': seconds_to_hms(duration_seconds),
            'transcript_source': f'whisper-{args.model}-asr',
            'language': transcript_data.get('language'),
            'source_urls': {
                'episode_page': item.get('link'),
            },
            'notes': [
                'Transcript generated from podcast audio via Whisper.',
                'No public transcript field was used in this run.',
            ],
            'description': item.get('description'),
            'segment_count': len(transcript_data.get('segments', [])),
            'text_length': len(transcript_data.get('text', '')),
            'guid': item.get('guid'),
        }
        meta_target.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8')
        write_clean_markdown(clean_target, metadata, transcript_data)

        if audio_dir:
            final_audio = audio_dir / f'{base}.mp3'
            shutil.copy2(audio_path, final_audio)

    return {'status': 'done', 'title': item['title'], 'base': base}


def main() -> int:
    parser = argparse.ArgumentParser(description='Download recent podcast episodes from an RSS feed and transcribe them with Whisper.')
    parser.add_argument('--feed-url', required=True)
    parser.add_argument('--show-slug', required=True)
    parser.add_argument('--limit', type=int, default=1)
    parser.add_argument('--episode-number')
    parser.add_argument('--title-contains')
    parser.add_argument('--language', default='Chinese')
    parser.add_argument('--model', default='turbo')
    parser.add_argument('--project-root', default='.')
    parser.add_argument('--keep-audio', action='store_true')
    parser.add_argument('--force', action='store_true')
    parser.add_argument('--verbose-whisper', action='store_true')
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    feed_meta = parse_feed(args.feed_url)
    items = select_items(feed_meta['items'], args)
    if not items:
        print('No matching episodes found', file=sys.stderr)
        return 1

    run_meta = {
        'started_at': datetime.now(timezone.utc).isoformat(),
        'show_slug': args.show_slug,
        'show_title': feed_meta['show_title'],
        'limit': args.limit,
        'episode_number': args.episode_number,
        'title_contains': args.title_contains,
        'episodes': [],
    }
    status_dir = project_root / 'metadata' / 'runs'
    status_dir.mkdir(parents=True, exist_ok=True)
    status_file = status_dir / f'{args.show_slug}-last-run.json'
    status_file.write_text(json.dumps(run_meta, ensure_ascii=False, indent=2), encoding='utf-8')

    for idx, item in enumerate(items, start=1):
        print(f"[{idx}/{len(items)}] {item['title']}", flush=True)
        result = process_episode(item, feed_meta, args, project_root)
        run_meta['episodes'].append(result)
        status_file.write_text(json.dumps(run_meta, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(result, ensure_ascii=False), flush=True)

    run_meta['completed_at'] = datetime.now(timezone.utc).isoformat()
    status_file.write_text(json.dumps(run_meta, ensure_ascii=False, indent=2), encoding='utf-8')
    print('DONE', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
