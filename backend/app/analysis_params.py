"""Strict raw query parsing, including duplicates; no database access."""
import re
from app.analysis_store import resolve_step_id


class AnalysisQueryInvalid(ValueError):
    pass


def parse_analysis_query(pairs: list[tuple[str, str]], allow_limit: bool) -> tuple[str, int]:
    allowed = {'step_id', 'limit'} if allow_limit else {'step_id'}
    values = dict(pairs)
    if len(values) != len(pairs) or not set(values) <= allowed or 'step_id' not in values:
        raise AnalysisQueryInvalid('invalid analysis parameters')
    step_id = values['step_id']
    if not re.fullmatch(r'S[0-9]{2}_T[0-9]{2}', step_id):
        raise AnalysisQueryInvalid('invalid analysis parameters')
    raw_limit = values.get('limit', '200')
    if not re.fullmatch(r'[0-9]+', raw_limit):
        raise AnalysisQueryInvalid('invalid analysis parameters')
    significant = raw_limit.lstrip('0') or '0'
    if len(significant) > 3 or not 1 <= int(significant) <= 500:
        raise AnalysisQueryInvalid('invalid analysis parameters')
    resolve_step_id(step_id)
    return step_id, int(significant)
