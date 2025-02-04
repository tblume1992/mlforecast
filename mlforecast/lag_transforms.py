# AUTOGENERATED! DO NOT EDIT! File to edit: ../nbs/lag_transforms.ipynb.

# %% auto 0
__all__ = ['RollingMean', 'RollingStd', 'RollingMin', 'RollingMax', 'RollingQuantile', 'SeasonalRollingMean',
           'SeasonalRollingStd', 'SeasonalRollingMin', 'SeasonalRollingMax', 'SeasonalRollingQuantile', 'ExpandingMean',
           'ExpandingStd', 'ExpandingMin', 'ExpandingMax', 'ExpandingQuantile', 'ExponentiallyWeightedMean']

# %% ../nbs/lag_transforms.ipynb 3
from typing import Optional

import numpy as np

try:
    import coreforecast.lag_transforms as core_tfms
    from coreforecast.grouped_array import GroupedArray as CoreGroupedArray
except ImportError:
    raise ImportError(
        "The lag_transforms module requires the coreforecast package. "
        "Please install it with `pip install coreforecast`.\n"
        'You can also install mlforecast with the lag_transforms extra: `pip install "mlforecast[lag_transforms]"`'
    ) from None
from sklearn.base import BaseEstimator

# %% ../nbs/lag_transforms.ipynb 4
class BaseLagTransform(BaseEstimator):
    _core_tfm: core_tfms.BaseLagTransform

    def transform(self, ga: CoreGroupedArray) -> np.ndarray:
        return self._core_tfm.transform(ga)

    def update(self, ga: CoreGroupedArray) -> np.ndarray:
        return self._core_tfm.update(ga)

# %% ../nbs/lag_transforms.ipynb 5
class Lag(BaseLagTransform):
    def __init__(self, lag: int):
        self.lag = lag
        self._core_tfm = core_tfms.Lag(lag=lag)

    def __eq__(self, other):
        return isinstance(other, Lag) and self.lag == other.lag

# %% ../nbs/lag_transforms.ipynb 6
class RollingBase(BaseLagTransform):
    "Rolling statistic"

    def __init__(self, window_size: int, min_samples: Optional[int] = None):
        """
        Parameters
        ----------
        window_size : int
            Number of samples in the window.
        min_samples: int
            Minimum samples required to output the statistic.
            If `None`, will be set to `window_size`.
        """
        self.window_size = window_size
        self.min_samples = min_samples

    def _set_core_tfm(self, lag: int):
        self._core_tfm = getattr(core_tfms, self.tfm_name)(
            lag=lag, window_size=self.window_size, min_samples=self.min_samples
        )
        return self

# %% ../nbs/lag_transforms.ipynb 7
class RollingMean(RollingBase):
    tfm_name = "RollingMean"


class RollingStd(RollingBase):
    tfm_name = "RollingStd"


class RollingMin(RollingBase):
    tfm_name = "RollingMin"


class RollingMax(RollingBase):
    tfm_name = "RollingMax"


class RollingQuantile(RollingBase):
    def __init__(self, p: float, window_size: int, min_samples: Optional[int] = None):
        super().__init__(window_size=window_size, min_samples=min_samples)
        self.p = p

    def _set_core_tfm(self, lag: int):
        self._core_tfm = core_tfms.RollingQuantile(
            lag=lag,
            p=self.p,
            window_size=self.window_size,
            min_samples=self.min_samples,
        )
        return self

# %% ../nbs/lag_transforms.ipynb 9
class SeasonalRollingBase(BaseLagTransform):
    """Rolling statistic over seasonal periods"""

    def __init__(
        self, season_length: int, window_size: int, min_samples: Optional[int] = None
    ):
        """
        Parameters
        ----------
        season_length : int
            Periodicity of the seasonal period.
        window_size : int
            Number of samples in the window.
        min_samples: int
            Minimum samples required to output the statistic.
            If `None`, will be set to `window_size`.
        """
        self.season_length = season_length
        self.window_size = window_size
        self.min_samples = min_samples

    def _set_core_tfm(self, lag: int):
        self._core_tfm = getattr(core_tfms, self.tfm_name)(
            lag=lag,
            season_length=self.season_length,
            window_size=self.window_size,
            min_samples=self.min_samples,
        )
        return self

# %% ../nbs/lag_transforms.ipynb 10
class SeasonalRollingMean(SeasonalRollingBase):
    tfm_name = "SeasonalRollingMean"


class SeasonalRollingStd(SeasonalRollingBase):
    tfm_name = "SeasonalRollingStd"


class SeasonalRollingMin(SeasonalRollingBase):
    tfm_name = "SeasonalRollingMin"


class SeasonalRollingMax(SeasonalRollingBase):
    tfm_name = "SeasonalRollingMax"


class SeasonalRollingQuantile(SeasonalRollingBase):
    def __init__(
        self,
        p: float,
        season_length: int,
        window_size: int,
        min_samples: Optional[int] = None,
    ):
        super().__init__(
            season_length=season_length,
            window_size=window_size,
            min_samples=min_samples,
        )
        self.p = p

    def _set_core_tfm(self, lag: int):
        self._core_tfm = core_tfms.SeasonalRollingQuantile(
            lag=lag,
            p=self.p,
            season_length=self.season_length,
            window_size=self.window_size,
            min_samples=self.min_samples,
        )
        return self

# %% ../nbs/lag_transforms.ipynb 12
class ExpandingBase(BaseLagTransform):
    """Expanding statistic"""

    def __init__(self):
        ...

    def _set_core_tfm(self, lag: int):
        self._core_tfm = getattr(core_tfms, self.tfm_name)(lag=lag)
        return self

# %% ../nbs/lag_transforms.ipynb 13
class ExpandingMean(ExpandingBase):
    tfm_name = "ExpandingMean"


class ExpandingStd(ExpandingBase):
    tfm_name = "ExpandingStd"


class ExpandingMin(ExpandingBase):
    tfm_name = "ExpandingMin"


class ExpandingMax(ExpandingBase):
    tfm_name = "ExpandingMax"


class ExpandingQuantile(ExpandingBase):
    def __init__(self, p: float):
        self.p = p

    def _set_core_tfm(self, lag: int):
        self._core_tfm = core_tfms.ExpandingQuantile(lag=lag, p=self.p)
        return self

# %% ../nbs/lag_transforms.ipynb 15
class ExponentiallyWeightedMean(BaseLagTransform):
    """Exponentially weighted average"""

    def __init__(self, alpha: float):
        """
        Parameters
        ----------
        alpha : float
            Smoothing factor.
        """
        self.alpha = alpha

    def _set_core_tfm(self, lag: int):
        self._core_tfm = core_tfms.ExponentiallyWeightedMean(lag=lag, alpha=self.alpha)
        return self
