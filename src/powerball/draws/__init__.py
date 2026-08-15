"""Core lottery domain: rules, historical draw data, stats, and pick generation.

`rules.py` is the single source of truth for game constants; `data.py` loads and validates
historical draws against those rules; `stats.py` derives frequency/pattern analysis from draws;
`picker.py` generates ticket picks (uniform or history-weighted) on top of `stats.py`.
"""
