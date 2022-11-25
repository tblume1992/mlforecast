# AUTOGENERATED! DO NOT EDIT! File to edit: ../nbs/lgb_cv.ipynb.

# %% auto 0
__all__ = ['LightGBMCV']

# %% ../nbs/lgb_cv.ipynb 3
import copy
import os
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple, Union

import lightgbm as lgb
import numpy as np
import pandas as pd

from mlforecast.core import (
    DateFeature,
    Differences,
    Freq,
    LagTransforms,
    Lags,
    TimeSeries,
)
from .forecast import Forecast
from .utils import backtest_splits

# %% ../nbs/lgb_cv.ipynb 5
def _mape(y_true, y_pred):
    abs_pct_err = abs(y_true - y_pred) / y_true
    return (
        abs_pct_err.groupby(y_true.index.get_level_values(0), observed=True)
        .mean()
        .mean()
    )


def _rmse(y_true, y_pred):
    sq_err = (y_true - y_pred) ** 2
    return (
        sq_err.groupby(y_true.index.get_level_values(0), observed=True)
        .mean()
        .pow(0.5)
        .mean()
    )


_metric2fn = {"mape": _mape, "rmse": _rmse}


def _update(bst, n):
    for _ in range(n):
        bst.update()


def _predict(ts, bst, valid, h, time_col, dynamic_dfs, predict_fn, **predict_fn_kwargs):
    preds = ts.predict(bst, h, dynamic_dfs, predict_fn, **predict_fn_kwargs).set_index(
        time_col, append=True
    )
    return valid.join(preds)


def _update_and_predict(
    ts, bst, valid, n, h, time_col, dynamic_dfs, predict_fn, **predict_fn_kwargs
):
    _update(bst, n)
    return _predict(
        ts, bst, valid, h, time_col, dynamic_dfs, predict_fn, **predict_fn_kwargs
    )

# %% ../nbs/lgb_cv.ipynb 6
CVResult = Tuple[int, float]

# %% ../nbs/lgb_cv.ipynb 7
class LightGBMCV:
    def __init__(
        self,
        freq: Optional[Freq] = None,
        lags: Optional[Lags] = None,
        lag_transforms: Optional[LagTransforms] = None,
        date_features: Optional[Iterable[DateFeature]] = None,
        differences: Optional[Differences] = None,
        num_threads: int = 1,
    ):
        """Create LightGBM CV object.

        Parameters
        ----------
        freq : str or int, optional (default=None)
            Pandas offset alias, e.g. 'D', 'W-THU' or integer denoting the frequency of the series.
        lags : list of int, optional (default=None)
            Lags of the target to use as features.
        lag_transforms : dict of int to list of functions, optional (default=None)
            Mapping of target lags to their transformations.
        date_features : list of str or callable, optional (default=None)
            Features computed from the dates. Can be pandas date attributes or functions that will take the dates as input.
        differences : list of int, optional (default=None)
            Differences to take of the target before computing the features. These are restored at the forecasting step.
        num_threads : int (default=1)
            Number of threads to use when computing the features.
        """
        self.num_threads = num_threads
        cpu_count = os.cpu_count()
        if cpu_count is None:
            num_cpus = 1
        else:
            num_cpus = cpu_count
        self.bst_threads = max(num_cpus // num_threads, 1)
        self.ts = TimeSeries(
            freq, lags, lag_transforms, date_features, differences, self.bst_threads
        )

    def __repr__(self):
        return (
            f"{self.__class__.__name__}("
            f"freq={self.ts.freq}, "
            f"lag_features={list(self.ts.transforms.keys())}, "
            f"date_features={self.ts.date_features}, "
            f"num_threads={self.num_threads}, "
            f"bst_threads={self.bst_threads})"
        )

    def setup(
        self,
        data: pd.DataFrame,
        n_windows: int,
        window_size: int,
        id_col: str,
        time_col: str,
        target_col: str,
        params: Optional[Dict[str, Any]] = None,
        static_features: Optional[List[str]] = None,
        dropna: bool = True,
        keep_last_n: Optional[int] = None,
        weights: Optional[Sequence[float]] = None,
        metric: Union[str, Callable] = "mape",
    ):
        """Initialize internal data structures to iteratively train the boosters. Use this before calling partial_fit.

        Parameters
        ----------
        data : pandas DataFrame
            Series data in long format.
        n_windows : int
            Number of windows to evaluate.
        window_size : int
            Number of test periods in each window.
        id_col : str
            Column that identifies each serie. If 'index' then the index is used.
        time_col : str
            Column that identifies each timestep, its values can be timestamps or integers.
        target_col : str
            Column that contains the target.
        params : dict, optional(default=None)
            Parameters to be passed to the LightGBM Boosters.
        static_features : list of str, optional (default=None)
            Names of the features that are static and will be repeated when forecasting.
        dropna : bool (default=True)
            Drop rows with missing values produced by the transformations.
        keep_last_n : int, optional (default=None)
            Keep only these many records from each serie for the forecasting step. Can save time and memory if your features allow it.
        weights : sequence of float, optional (default=None)
            Weights to multiply the metric of each window. If None, all windows have the same weight.
        metric : str or callable, default='mape'
            Metric used to assess the performance of the models and perform early stopping.

        Returns
        -------
        self : LightGBMCV
            CV object with internal data structures for partial_fit.
        """
        if weights is None:
            self.weights = np.full(n_windows, 1 / n_windows)
        elif len(weights) != n_windows:
            raise ValueError("Must specify as many weights as the number of windows")
        else:
            self.weights = np.asarray(weights)
        if callable(metric):
            self.metric_fn = metric
            self.metric_name = "custom_metric"
        else:
            if metric not in _metric2fn:
                raise ValueError(
                    f'{metric} is not one of the implemented metrics: ({", ".join(_metric2fn.keys())})'
                )
            self.metric_fn = _metric2fn[metric]
            self.metric_name = metric

        if id_col != "index":
            data = data.set_index(id_col)

        if np.issubdtype(data[time_col].dtype.type, np.integer):
            freq = 1
        else:
            freq = self.ts.freq
        self.items = []
        self.window_size = window_size
        self.time_col = time_col
        self.target_col = target_col
        params = {} if params is None else params
        for _, train, valid in backtest_splits(
            data, n_windows, window_size, freq, time_col
        ):
            ts = copy.deepcopy(self.ts)
            prep = ts.fit_transform(
                train,
                "index",
                time_col,
                target_col,
                static_features,
                dropna,
                keep_last_n,
            )
            ds = lgb.Dataset(
                prep.drop(columns=[time_col, target_col]), prep[target_col]
            ).construct()
            bst = lgb.Booster({**params, "num_threads": self.bst_threads}, ds)
            bst.predict = partial(bst.predict, num_threads=self.bst_threads)
            valid = valid.set_index(time_col, append=True)
            self.items.append((ts, bst, valid))
        return self

    def _single_threaded_partial_fit(
        self,
        metric_values,
        num_iterations,
        dynamic_dfs,
        predict_fn,
        **predict_fn_kwargs,
    ):
        for j, (ts, bst, valid) in enumerate(self.items):
            preds = _update_and_predict(
                ts,
                bst,
                valid,
                num_iterations,
                self.window_size,
                self.time_col,
                dynamic_dfs,
                predict_fn,
                **predict_fn_kwargs,
            )
            metric_values[j] = self.metric_fn(preds[self.target_col], preds["Booster"])

    def _multithreaded_partial_fit(
        self,
        metric_values,
        num_iterations,
        dynamic_dfs,
        predict_fn,
        **predict_fn_kwargs,
    ):
        with ThreadPoolExecutor(self.num_threads) as executor:
            futures = []
            for ts, bst, valid in self.items:
                _update(bst, num_iterations)
                future = executor.submit(
                    _predict,
                    ts,
                    bst,
                    valid,
                    self.window_size,
                    self.time_col,
                    dynamic_dfs,
                    predict_fn,
                    **predict_fn_kwargs,
                )
                futures.append(future)
            cv_preds = [f.result() for f in futures]
        metric_values[:] = [
            self.metric_fn(preds[self.target_col], preds["Booster"])
            for preds in cv_preds
        ]

    def partial_fit(
        self,
        num_iterations: int,
        dynamic_dfs: Optional[List[pd.DataFrame]] = None,
        predict_fn: Optional[Callable] = None,
        **predict_fn_kwargs,
    ) -> float:
        """Train the boosters for some iterations.

        Parameters
        ----------
        num_iterations : int
            Number of boosting iterations to run
        dynamic_dfs : list of pandas DataFrame, optional (default=None)
            Future values of the dynamic features, e.g. prices.
        predict_fn : callable, optional (default=None)
            Custom function to compute predictions.
            This function will recieve: model, new_x, dynamic_dfs, features_order and kwargs,
            and should return an array with the predictions, where:
                model : regressor
                    Fitted model.
                new_x : pandas DataFrame
                    Current values of the features.
                dynamic_dfs : list of pandas DataFrame
                    Future values of the dynamic features
                features_order : list of str
                    Column names in the order in which they were used to train the model.
                **kwargs
                    Other keyword arguments passed to `Forecast.predict`.
        **predict_fn_kwargs
            Additional arguments passed to predict_fn

        Returns
        -------
        metric_value : float
            Weighted metric after training for num_iterations.
        """
        metric_values = np.empty(len(self.items))
        if self.num_threads == 1:
            self._single_threaded_partial_fit(
                metric_values,
                num_iterations,
                dynamic_dfs,
                predict_fn,
                **predict_fn_kwargs,
            )
        else:
            self._multithreaded_partial_fit(
                metric_values,
                num_iterations,
                dynamic_dfs,
                predict_fn,
                **predict_fn_kwargs,
            )
        return metric_values @ self.weights

    def _should_stop(self, hist, early_stopping_evals, early_stopping_pct) -> bool:
        if len(hist) < early_stopping_evals + 1:
            return False
        improvement_pct = 1 - hist[-1][1] / hist[-(early_stopping_evals + 1)][1]
        return improvement_pct < early_stopping_pct

    def _best_iter(self, hist, early_stopping_evals) -> int:
        best_iter, best_score = hist[-1]
        for r, m in hist[-(early_stopping_evals + 1) : -1]:
            if m < best_score:
                best_score = m
                best_iter = r
        return best_iter

    def fit(
        self,
        data: pd.DataFrame,
        n_windows: int,
        window_size: int,
        id_col: str,
        time_col: str,
        target_col: str,
        num_iterations: int = 100,
        params: Optional[Dict[str, Any]] = None,
        static_features: Optional[List[str]] = None,
        dropna: bool = True,
        keep_last_n: Optional[int] = None,
        dynamic_dfs: Optional[List[pd.DataFrame]] = None,
        eval_every: int = 10,
        weights: Optional[Sequence[float]] = None,
        metric: Union[str, Callable] = "mape",
        verbose_eval: bool = True,
        early_stopping_evals: int = 2,
        early_stopping_pct: float = 0.01,
        compute_cv_preds: bool = False,
        fit_on_all: bool = False,
        predict_fn: Optional[Callable] = None,
        **predict_fn_kwargs,
    ) -> List[CVResult]:
        """Train boosters simultaneously and assess their performance on the complete forecasting window.

        Parameters
        ----------
        data : pandas DataFrame
            Series data in long format.
        n_windows : int
            Number of windows to evaluate.
        window_size : int
            Number of test periods in each window.
        id_col : str
            Column that identifies each serie. If 'index' then the index is used.
        time_col : str
            Column that identifies each timestep, its values can be timestamps or integers.
        target_col : str
            Column that contains the target.
        num_iterations : int (default=100)
            Maximum number of boosting iterations to run.
        params : dict, optional(default=None)
            Parameters to be passed to the LightGBM Boosters.
        static_features : list of str, optional (default=None)
            Names of the features that are static and will be repeated when forecasting.
        dropna : bool (default=True)
            Drop rows with missing values produced by the transformations.
        keep_last_n : int, optional (default=None)
            Keep only these many records from each serie for the forecasting step. Can save time and memory if your features allow it.
        dynamic_dfs : list of pandas DataFrame, optional (default=None)
            Future values of the dynamic features, e.g. prices.
        eval_every : int (default=10)
            Number of boosting iterations to train before evaluating on the whole forecast window.
        weights : sequence of float, optional (default=None)
            Weights to multiply the metric of each window. If None, all windows have the same weight.
        metric : str or callable, default='mape'
            Metric used to assess the performance of the models and perform early stopping.
        verbose_eval : bool
            Print the metrics of each evaluation.
        early_stopping_evals : int (default=2)
            Maximum number of evaluations to run without improvement.
        early_stopping_pct : float (default=0.01)
            Minimum percentage improvement in metric value in `early_stopping_evals` evaluations.
        compute_cv_preds : bool (default=True)
            Compute predictions for each window after finding the best iteration.
        fit_on_all : bool (default=True)
            Return model fitted on full dataset.
        predict_fn : callable, optional (default=None)
            Custom function to compute predictions.
            This function will recieve: model, new_x, dynamic_dfs, features_order and kwargs,
            and should return an array with the predictions, where:
                model : regressor
                    Fitted model.
                new_x : pandas DataFrame
                    Current values of the features.
                dynamic_dfs : list of pandas DataFrame
                    Future values of the dynamic features
                features_order : list of str
                    Column names in the order in which they were used to train the model.
                **kwargs
                    Other keyword arguments passed to `Forecast.predict`.
        **predict_fn_kwargs
            Additional arguments passed to predict_fn

        Returns
        -------
        cv_result : list of tuple.
            List of (boosting rounds, metric value) tuples.
        """
        self.setup(
            data=data,
            n_windows=n_windows,
            window_size=window_size,
            params=params,
            id_col=id_col,
            time_col=time_col,
            target_col=target_col,
            static_features=static_features,
            dropna=dropna,
            keep_last_n=keep_last_n,
            weights=weights,
            metric=metric,
        )
        hist = []
        for i in range(0, num_iterations, eval_every):
            metric_value = self.partial_fit(
                eval_every, dynamic_dfs, predict_fn, **predict_fn_kwargs
            )
            rounds = eval_every + i
            hist.append((rounds, metric_value))
            if verbose_eval:
                print(f"[{rounds:,d}] {self.metric_name}: {metric_value:,f}")
            if self._should_stop(hist, early_stopping_evals, early_stopping_pct):
                print(f"Early stopping at round {rounds:,}")
                break
        rounds = self._best_iter(hist, early_stopping_evals)
        print(f"Using best iteration: {rounds:,}")
        hist = hist[: rounds // eval_every]
        for _, bst, _ in self.items:
            bst.best_iteration = rounds

        self.cv_models_ = [item[1] for item in self.items]
        if compute_cv_preds:
            with ThreadPoolExecutor(self.num_threads) as executor:
                futures = []
                for ts, bst, valid in self.items:
                    future = executor.submit(
                        _predict,
                        ts,
                        bst,
                        valid,
                        window_size,
                        time_col,
                        dynamic_dfs,
                        predict_fn,
                        **predict_fn_kwargs,
                    )
                    futures.append(future)
                self.cv_preds_ = pd.concat(
                    [f.result().assign(window=i) for i, f in enumerate(futures)]
                )

        if fit_on_all:
            self.fcst = Forecast([])
            self.fcst.ts = self.ts
            params = params if params is not None else {}
            self.fcst.models = [lgb.LGBMRegressor(**{**params, "n_estimators": rounds})]
            self.fcst.fit(
                data,
                id_col,
                time_col,
                target_col,
                static_features,
                dropna,
                keep_last_n,
            )
        else:
            if id_col != "index":
                data = data.set_index(id_col)
            self.ts._fit(
                data, "index", time_col, target_col, static_features, keep_last_n
            )
        return hist

    def predict(
        self,
        horizon: int,
        dynamic_dfs: Optional[List[pd.DataFrame]] = None,
        predict_fn: Optional[Callable] = None,
        **predict_fn_kwargs,
    ) -> pd.DataFrame:
        """Compute predictions using the model trained on all data.

        Parameters
        ----------
        horizon : int
            Number of periods to predict.
        dynamic_dfs : list of pandas DataFrame, optional (default=None)
            Future values of the dynamic features, e.g. prices.
        predict_fn : callable, optional (default=None)
            Custom function to compute predictions.
            This function will recieve: model, new_x, dynamic_dfs, features_order and kwargs,
            and should return an array with the predictions, where:
                model : regressor
                    Fitted model.
                new_x : pandas DataFrame
                    Current values of the features.
                dynamic_dfs : list of pandas DataFrame
                    Future values of the dynamic features
                features_order : list of str
                    Column names in the order in which they were used to train the model.
                **kwargs
                    Other keyword arguments passed to `Forecast.predict`.
        **predict_fn_kwargs
            Additional arguments passed to predict_fn

        Returns
        -------
        result : pandas DataFrame
            Predictions for each serie and timestep.
        """
        if not hasattr(self, "fcst"):
            raise ValueError(
                "Must call fit with fit_on_all=True before. You can also call cv_predict instead."
            )
        return self.fcst.predict(horizon, dynamic_dfs, predict_fn, **predict_fn_kwargs)

    def cv_predict(
        self,
        horizon: int,
        dynamic_dfs: Optional[List[pd.DataFrame]] = None,
        predict_fn: Optional[Callable] = None,
        **predict_fn_kwargs,
    ) -> pd.DataFrame:
        """Compute predictions with each of the trained boosters.

        Parameters
        ----------
        horizon : int
            Number of periods to predict.
        dynamic_dfs : list of pandas DataFrame, optional (default=None)
            Future values of the dynamic features, e.g. prices.
        predict_fn : callable, optional (default=None)
            Custom function to compute predictions.
            This function will recieve: model, new_x, dynamic_dfs, features_order and kwargs,
            and should return an array with the predictions, where:
                model : regressor
                    Fitted model.
                new_x : pandas DataFrame
                    Current values of the features.
                dynamic_dfs : list of pandas DataFrame
                    Future values of the dynamic features
                features_order : list of str
                    Column names in the order in which they were used to train the model.
                **kwargs
                    Other keyword arguments passed to `Forecast.predict`.
        **predict_fn_kwargs
            Additional arguments passed to predict_fn

        Returns
        -------
        result : pandas DataFrame
            Predictions for each serie and timestep, with one column per window.
        """
        return self.ts.predict(
            self.cv_models_, horizon, dynamic_dfs, predict_fn, **predict_fn_kwargs
        )
