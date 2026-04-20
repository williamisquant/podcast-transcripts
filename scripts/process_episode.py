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


def choose_sections(text: str) -> list[str]:
    sections: list[str] = []
    if any(k in text for k in ['美股', '台股', '大盤', '指數']):
        sections.append('總經 / 盤勢')
    if any(k in text for k in ['台積電', '記憶體', 'CPU', 'GPU', '封裝', '供應鏈', '光通', '被動元件']):
        sections.append('產業 / 供應鏈')
    if any(k in text for k in ['台積電', '聯發科', '國巨', '萬潤', '均華', '致茂', 'NVIDIA', 'Google', 'Tesla']):
        sections.append('個股 / 公司觀察')
    if any(k in text for k in ['健康', '成功', '小孩', '家人', '老婆', '人生']):
        sections.append('人生觀 / 價值觀')
    if '開場 / 生活話題' not in sections:
        sections.insert(0, '開場 / 生活話題')
    if '其他' not in sections:
        sections.append('其他')
    return sections


def build_summary(meta: dict[str, Any], clean_path: Path, show_name: str, host: str) -> str:
    text = clean_path.read_text(encoding='utf-8')
    sections = choose_sections(text)
    lines = [
        f"# Gooaye {meta.get('episode_title', '')} 摘要" if show_name == '股癌' else f"# {show_name} {meta.get('episode_title', '')} 摘要",
        '',
        f"- 節目：{show_name}",
        f"- 主持人：{host or meta.get('host', '')}",
        f"- 集數：{meta.get('episode_title', '')}",
        f"- 日期：{meta.get('published_date', '')}",
        '- 來源：流程自動產生的摘要草稿（建議後續人工校修）',
        '',
    ]
    for sec in sections:
        lines.append(f'## {sec}')
        lines.append('')
        if sec == '開場 / 生活話題':
            lines.append('- 待人工補寫：先根據前段逐字稿整理開場、業配與生活話題。')
        elif sec == '總經 / 盤勢':
            lines.append('- 待人工補寫：整理美股 / 台股 / 大盤與資金風格重點。')
        elif sec == '產業 / 供應鏈':
            lines.append('- 待人工補寫：整理供應鏈、產業催化與稼動率 / 缺貨 / 建置等資訊。')
        elif sec == '個股 / 公司觀察':
            lines.append('- 待人工補寫：整理節目中提及的公司、族群與投資觀察。')
        elif sec == '人生觀 / 價值觀':
            lines.append('- 待人工補寫：整理健康、家庭、成功、人生觀等段落。')
        else:
            lines.append('- 待人工補寫：補充 QA、生活雜談與其他零碎重點。')
        lines.append('')
    lines.append('## 一句話總結')
    lines.append('')
    lines.append('- 待人工補寫：用一句話濃縮本集核心觀點。')
    lines.append('')
    return '\n'.join(lines)


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
    summaries_dir = project_root / 'metadata' / 'summaries'
    reviews_dir.mkdir(parents=True, exist_ok=True)
    summaries_dir.mkdir(parents=True, exist_ok=True)

    uncertain = extract_uncertain_terms(clean_path)
    uncertain_path = reviews_dir / f'{base}-uncertain-terms.json'
    if args.overwrite_artifacts or not uncertain_path.exists():
        uncertain_path.write_text(json.dumps(uncertain, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    summary = build_summary(meta, clean_path, cfg['show_name'], cfg['host'])
    summary_path = summaries_dir / f'{base}-summary.md'
    if args.overwrite_artifacts or not summary_path.exists():
        summary_path.write_text(summary, encoding='utf-8')

    print(json.dumps({
        'base': base,
        'episode_metadata': str((project_root / 'metadata' / 'episodes' / f'{base}-metadata.json')),
        'clean_transcript': str(clean_path),
        'uncertain_terms': str(uncertain_path),
        'summary': str(summary_path),
        'uncertain_count': len(uncertain),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
