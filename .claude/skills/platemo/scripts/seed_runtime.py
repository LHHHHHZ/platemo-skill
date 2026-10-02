# -*- coding: utf-8 -*-
"""只校验通用 MATLAB 随机性证据；外部随机源由适配器负责。"""


def randomness_issues(record):
    try:
        seed = record['seed']
        if type(seed) is not int or not 0 <= seed < 2**32:
            raise ValueError('Invalid run seed')
        matlab = record['randomness']['matlab']
        if (matlab['seed'] != seed or matlab['generator'] != 'twister'
                or matlab['initialized_before_problem'] is not True):
            raise ValueError('MATLAB randomness was not initialized before problem construction')
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        return [{'code': 'randomness_unverified', 'message': str(exc)}]
    return []
