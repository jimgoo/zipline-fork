#
# Copyright 2013 Quantopian, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import functools

import logbook
import math
import numpy as np
import numpy.linalg as la

from six import iteritems

import pandas as pd

from . import risk
from . risk import (
    check_entry,
)

from empyrical import (
    alpha_beta_aligned,
    annual_volatility,
    cum_returns,
    downside_risk,
    information_ratio,
    max_drawdown,
    sharpe_ratio,
    sortino_ratio
)


from zipline.utils.serialization_utils import (
    VERSION_LABEL
)

log = logbook.Logger('Risk Period')

choose_treasury = functools.partial(risk.choose_treasury,
                                    risk.select_treasury_duration)


class RiskMetricsPeriod(object):
    def __init__(self, start_date, end_date, returns, env,
                 benchmark_returns=None, algorithm_leverages=None):

        self.env = env
        treasury_curves = env.treasury_curves
        if treasury_curves.index[-1] >= start_date:
            mask = ((treasury_curves.index >= start_date) &
                    (treasury_curves.index <= end_date))

            self.treasury_curves = treasury_curves[mask]
        else:
            # our test is beyond the treasury curve history
            # so we'll use the last available treasury curve
            self.treasury_curves = treasury_curves[-1:]

        self.start_date = start_date
        self.end_date = end_date

        if benchmark_returns is None:
            br = env.benchmark_returns
            benchmark_returns = br[(br.index >= returns.index[0]) &
                                   (br.index <= returns.index[-1])]

        self.algorithm_returns = self.mask_returns_to_period(returns,
                                                             env)
        self.benchmark_returns = self.mask_returns_to_period(benchmark_returns,
                                                             env)
        self.algorithm_leverages = algorithm_leverages

        self.calculate_metrics()

    def calculate_metrics(self):
        #print('-'*100)
        #print(self.benchmark_returns.head())
	    #print(self.algorithm_returns.head())
        
        self.benchmark_period_returns = \
            cum_returns(self.benchmark_returns).iloc[-1]

        self.algorithm_period_returns = \
            cum_returns(self.algorithm_returns).iloc[-1]

        # fix the case when the indices don't match
        if not self.algorithm_returns.index.equals(self.benchmark_returns.index):
            joined = self.algorithm_returns.align(self.benchmark_returns, join='outer')
            self.algorithm_returns = joined[0].fillna(method='ffill')
            self.benchmark_returns = joined[1].fillna(method='ffill')

        if not self.algorithm_returns.index.equals(self.benchmark_returns.index):
            message = "Mismatch between benchmark_returns ({bm_count}) and \
            algorithm_returns ({algo_count}) in range {start} : {end}"
            message = message.format(
                bm_count=len(self.benchmark_returns),
                algo_count=len(self.algorithm_returns),
                start=self.start_date,
                end=self.end_date
            )
            # save for debugging
            import pickle
            pickle.dump((self.algorithm_returns, self.benchmark_returns), open('/tmp/zp-returns.pkl', 'wb'))
            raise Exception(message)

        self.num_trading_days = len(self.benchmark_returns)
        
        ## begin empyrical metrics
        self.mean_algorithm_returns = (
            self.algorithm_returns.cumsum() /
            np.arange(1, self.num_trading_days + 1, dtype=np.float64)
        )

        self.benchmark_volatility = annual_volatility(self.benchmark_returns)
        self.algorithm_volatility = annual_volatility(self.algorithm_returns)

        self.treasury_period_return = choose_treasury(
            self.treasury_curves,
            self.start_date,
            self.end_date,
            self.env,
        )
        self.sharpe = sharpe_ratio(
            self.algorithm_returns,
        )
        # The consumer currently expects a 0.0 value for sharpe in period,
        # this differs from cumulative which was np.nan.
        # When factoring out the sharpe_ratio, the different return types
        # were collapsed into `np.nan`.
        # TODO: Either fix consumer to accept `np.nan` or make the
        # `sharpe_ratio` return type configurable.
        # In the meantime, convert nan values to 0.0
        if pd.isnull(self.sharpe):
            self.sharpe = 0.0
        self.downside_risk = downside_risk(
            self.algorithm_returns.values
        )
        self.sortino = sortino_ratio(
            self.algorithm_returns.values,
            _downside_risk=self.downside_risk,
        )
        self.information = information_ratio(
            self.algorithm_returns.values,
            self.benchmark_returns.values,
        )
        self.alpha, self.beta = alpha_beta_aligned(
            self.algorithm_returns.values,
            self.benchmark_returns.values,
        )
        self.excess_return = self.algorithm_period_returns - \
            self.treasury_period_return
        self.max_drawdown = max_drawdown(self.algorithm_returns.values)

        self.max_leverage = self.calculate_max_leverage()

    def to_dict(self):
        """
        Creates a dictionary representing the state of the risk report.
        Returns a dict object of the form:
        """
        period_label = self.end_date.strftime("%Y-%m")
        rval = {
            'trading_days': self.num_trading_days,
            'benchmark_volatility': self.benchmark_volatility,
            'algo_volatility': self.algorithm_volatility,
            'treasury_period_return': self.treasury_period_return,
            'algorithm_period_return': self.algorithm_period_returns,
            'benchmark_period_return': self.benchmark_period_returns,
            'sharpe': self.sharpe,
            'sortino': self.sortino,
            'information': self.information,
            'beta': self.beta,
            'alpha': self.alpha,
            'excess_return': self.excess_return,
            'max_drawdown': self.max_drawdown,
            'max_leverage': self.max_leverage,
            'period_label': period_label
        }

        return {k: None if check_entry(k, v) else v
                for k, v in iteritems(rval)}

    def __repr__(self):
        statements = []
        metrics = [
            "algorithm_period_returns",
            "benchmark_period_returns",
            "excess_return",
            "num_trading_days",
            "benchmark_volatility",
            "algorithm_volatility",
            "sharpe",
            "sortino",
            "information",
            # "algorithm_covariance",
            # "benchmark_variance",
            "beta",
            "alpha",
            "max_drawdown",
            "max_leverage",
            "algorithm_returns",
            "benchmark_returns",
            # "condition_number",
            # "eigen_values"
        ]

        for metric in metrics:
            value = getattr(self, metric)
            statements.append("{m}:{v}".format(m=metric, v=value))

        return '\n'.join(statements)

    def mask_returns_to_period(self, daily_returns, env):
        if isinstance(daily_returns, list):
            returns = pd.Series([x.returns for x in daily_returns],
                                index=[x.date for x in daily_returns])
        else:  # otherwise we're receiving an index already
            returns = daily_returns

        trade_days = env.trading_days
        trade_day_mask = returns.index.normalize().isin(trade_days)

        mask = ((returns.index >= self.start_date) &
                (returns.index <= self.end_date) & trade_day_mask)

        returns = returns[mask]
        return returns

    def calculate_max_leverage(self):
        if self.algorithm_leverages is None:
            return 0.0
        else:
            return max(self.algorithm_leverages)

    def __getstate__(self):
        state_dict = {k: v for k, v in iteritems(self.__dict__)
                      if not k.startswith('_')}

        STATE_VERSION = 3
        state_dict[VERSION_LABEL] = STATE_VERSION

        return state_dict

    def __setstate__(self, state):

        OLDEST_SUPPORTED_STATE = 3
        version = state.pop(VERSION_LABEL)

        if version < OLDEST_SUPPORTED_STATE:
            raise BaseException("RiskMetricsPeriod saved state \
                    is too old.")

        self.__dict__.update(state)
