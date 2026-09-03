"""Forecasting foundation: canonical daily series, baselines and backtesting.

This package deliberately contains no model. Its job is to make a model
*provable*: a canonical daily series with the same trading semantics the rest
of the analytics layer uses, transparent baselines a real café already relies
on, and leakage-safe rolling-origin evaluation. Anything added later has to
beat these numbers under this harness or it does not belong in the product.
"""
