"""Project storage and per-run processing are separate budgets."""
MAX_STORED_MATERIALS = 100
MAX_STORED_CHARS = 480000
MAX_RUN_MATERIALS = 8
MAX_RUN_CHARS = 48000


def validate_scope(materials):
    from core.review import ReviewError
    if len(materials) > MAX_RUN_MATERIALS or sum(len(m['text']) for m in materials) > MAX_RUN_CHARS:
        raise ReviewError('本轮 AI 材料超出范围：最多 8 份、48,000 字。材料已保留，请到材料与来源调整本轮纳入；不会自动截断或排除。')
