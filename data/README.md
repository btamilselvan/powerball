# Data

`draws.csv` is the historical draw data used as the default dataset for the
CLI, API, and tests.

Format:

```
date,n1,n2,n3,n4,n5,powerball
"Wed, Jan 3, 2024",4,15,29,32,36,5
```

- header row is required but its column names aren't checked (columns are
  read positionally)
- `date`: quoted `Day, Mon D, YYYY` (e.g. `"Mon, Aug 3, 2026"`)
- `n1`-`n5`: the five white balls (1-69), any order
- `powerball`: the red ball (1-26)

To point the CLI or API at a different file, pass `--data path/to/file.csv`
(CLI) or replace this file (API always reads `data/draws.csv`, loaded once
at startup).
