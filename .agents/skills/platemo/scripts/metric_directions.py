"""指标方向解析，不使用可变全局默认值。"""
# PlatEMO 已知指标方向；未知指标必须明确声明。
LOWER_IS_BETTER = {
    "IGD", "GD", "IGDp", "IGDX", "Spacing", "Spread", "DeltaP", "CPF",
    "Min_value", "runtime", "Mean_IGD", "Worst_IGD",
    "Task1_IGD", "Task2_IGD", "Task1_Min_value", "Task2_Min_value",
    "Lower_level_Min_value", "Upper_level_Min_value",
}
HIGHER_IS_BETTER = {
    "HV", "PD", "DM", "Feasible_rate", "Mean_HV", "Worst_HV",
    "Task1_HV", "Task2_HV",
}


def resolve_directions(metrics, declared=None):
    declared = {} if declared is None else declared
    if not isinstance(declared, dict):
        raise ValueError('metric_directions must be an object mapping metric names to min/max')
    for name, direction in declared.items():
        if not isinstance(name, str) or not name or direction not in ('min', 'max'):
            raise ValueError('Metric directions must be min or max')
        known = 'min' if name in LOWER_IS_BETTER else 'max' if name in HIGHER_IS_BETTER else None
        if known is not None and direction != known:
            raise ValueError(f'Conflicting direction for known metric: {name}')
    result = {}
    for name in metrics:
        direction = declared.get(name, 'min' if name in LOWER_IS_BETTER else 'max' if name in HIGHER_IS_BETTER else None)
        if direction is None:
            raise ValueError(f'Unknown metric direction: {name}; declare metric_directions explicitly')
        result[name] = direction
    return result


def parse_directions(text):
    result = {}
    if not text:
        return result
    for item in text.split(','):
        parts = item.strip().split('=')
        if len(parts) != 2 or not parts[0] or parts[0] in result:
            raise ValueError('Use unique NAME=min or NAME=max metric directions')
        result[parts[0]] = parts[1]
    resolve_directions(result, result)
    return result
