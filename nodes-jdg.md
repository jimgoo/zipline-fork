# Nodes on how Zipline works

## `zipline/algorithm.py`

- Entry point for all algos is `self.run(sources)`. 

- `self.perf_tracker` is reset whenever `self.run` is called:

```python
if self.perf_tracker is None:
        # HACK: When running with the `run` method, we set perf_tracker to
        # None so that it will be overwritten here.
        self.perf_tracker = PerformanceTracker(
            sim_params=sim_params, env=self.trading_environment
        )
```

- `self.gen` is made in `self._create_generator` (`AlgorithmSimulator` is in `zipline/gens/tradesimulation.py`):

```python
self.trading_client = AlgorithmSimulator(self, sim_params)
...
self.trading_client.transform(self.data_gen)
```

which is used in the main `self.run` loop:

```python
perfs = []
for perf in self.gen:
    perfs.append(perf)
```

All calls to self.order get routed to `self.blotter.order` below.


## `zipline/finance/blotter.py`


