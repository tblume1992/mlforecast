# AUTOGENERATED! DO NOT EDIT! File to edit: ../nbs/compat.ipynb.

# %% auto 0
__all__ = []

# %% ../nbs/compat.ipynb 1
try:
    from catboost import CatBoostRegressor
    from window_ops.shift import shift_array
except ImportError:

    def shift_array(*_args, **_kwargs):
        raise Exception

    class CatBoostRegressor: ...
