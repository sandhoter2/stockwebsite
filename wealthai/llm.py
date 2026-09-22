"""OmniRoute LLM client — Groq for short books, OpenAI for richer reports.

Keys come from the *project* env (`USER_OMNIROUTE_API_KEY`), never from the
agent runtime. Both Groq and OpenAI are reached through the same OmniRoute
OpenAI-compatible chat/completions endpoint; `provider` only picks the model.
"""
import json
import os
import urllib.error
import urllib.request

from django.conf import settings

GROQ_MODEL = 'mixtral-8x7b-32768'
OPENAI_MODEL = 'gpt-4o'
DEFAULT_BASE = 'https://api.omniroute.ai/v1'


def choose_provider(requested, holdings_count=0):
    if requested in ('groq', 'openai'):
        return requested
    return 'openai' if (holdings_count or 0) >= 8 else 'groq'


def _fallback_report(prompt):
    return (
        '## Portfolio briefing (offline)\n\n'
        'OmniRoute is not configured (`USER_OMNIROUTE_API_KEY`). '
        'This is a local stand-in so the task still completes.\n\n'
        '```\n' + prompt[:1200] + '\n```\n'
    )


def complete(prompt, provider='auto', holdings_count=0):
    """Return (markdown, provider_used, model). Never raises."""
    chosen = choose_provider(provider, holdings_count)
    model = GROQ_MODEL if chosen == 'groq' else OPENAI_MODEL
    key = (getattr(settings, 'OMNIROUTE_API_KEY', '')
           or os.environ.get('USER_OMNIROUTE_API_KEY')
           or os.environ.get('USER_LLM_API_KEY'))
    base = (getattr(settings, 'OMNIROUTE_BASE_URL', '')
            or os.environ.get('USER_OMNIROUTE_BASE_URL')
            or DEFAULT_BASE).rstrip('/')
    if not key:
        return _fallback_report(prompt), chosen, model
    body = json.dumps({
        'model': model,
        'temperature': 0.3,
        'messages': [
            {'role': 'system', 'content': (
                'You are a concise portfolio analyst. Reply in Markdown with '
                'Performance, Risk, and Actionable recommendations. No hype.'
            )},
            {'role': 'user', 'content': prompt},
        ],
    }).encode('utf-8')
    req = urllib.request.Request(
        base + '/chat/completions',
        data=body,
        headers={
            'Authorization': 'Bearer ' + key,
            'Content-Type': 'application/json',
            'User-Agent': 'tradeguru-wealthai/1.0',
        },
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        text = data['choices'][0]['message']['content']
        used_model = (data.get('model') or model)
        return text, chosen, used_model
    except (urllib.error.URLError, urllib.error.HTTPError, KeyError, IndexError,
            ValueError, TimeoutError, OSError) as exc:
        return (
            '## Report unavailable\n\nOmniRoute call failed: ' + str(exc) + '\n',
            chosen, model,
        )
