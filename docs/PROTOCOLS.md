# Protocols: format for your own methods

Built-in protocols (in `specrec/protocols_builtin.py`):
- **МДА**: 532 + 600 nm, duplicates, C = (E532 − E600) × 4 / 0.156.
- **Каталаза**: H₂O₂ calibration → k; blanks, test tubes and sample backgrounds; 10 min per tube with a 30 s stagger.
- **СОД**: controls and test tubes; A₀ → 10 min → A₁₀; T, conventional units (у.о.), × 30.
- **SH-групи (Ellman)** with haemolysis (Harboe): Aфон at 412/380/415/450, DTNB, 15 min, Aзр.
- **Білок за Бредфордом**: 595 nm, 20 µl + 1 ml of reagent, 5 min; BSA 0–1.5 mg/ml, quadratic curve.
- **Білок за Лоурі**: 750 nm, reagent C → 10 min → Folin → 30 min; BSA 0–0.5 mg/ml, quadratic curve.
- Two templates: **кінцева точка** (an endpoint with a factor) and **калібрувальна крива + зразки** (a calibration curve with samples).

**Протокол → Змінити (моя копія)…** saves a copy as JSON in `SpecRec_data/protocols/` and
opens it in a text editor. After editing, press ⟳: the protocol appears in the list with a ✎.
If a file has a mistake, the list shows ⚠ and the program says what is wrong.

## Structure

```json
{
  "id": "mda_my",                       // unique, Latin letters
  "name": "МДА — моя копія",
  "source": "…", "description": "…",
  "prep": ["what to prepare", "…"],     // checklist before the series
  "timers": [{"label": "Кип'ятіння 10 хв", "seconds": 600}],
  "stagger": 30,                        // hint: start tubes with this offset, s
  "constants": {"dil": 4, "eps": 0.156},
  "inputs": {"dilution": {"label": "Розведення", "default": 1}},   // per-sample columns
  "calibration": {"type": "std", "x": [0, 4.41, 8.82], "unit": "мкмоль", "model": "linear", "prefix": "k"},
  "tubes": {
    "zero": {"label": "Контроль — нуль", "per": "series", "count": 1, "zero": true,
             "steps": [{"read": "E", "wl": [532, 600]}]},
    "test": {"label": "Проба {i}", "per": "sample", "count": 2,
             "steps": [{"do": "Додайте реагент — старт"},
                       {"wait": 600, "from": 0, "text": "10 хв"},
                       {"read": "E", "wl": [532, 600]}]}
  },
  "tube_calc":   {"test": {"Ek": "E_532 - E_600", "C": "Ek * dil / eps"}},
  "series_calc": {},
  "sample_calc": {"C": "mean(test.C) * dilution", "CV": "cv(test.C)"},
  "results": [{"var": "C", "label": "МДА", "unit": "мкмоль/л", "digits": 2},
              {"var": "CV", "label": "CV", "unit": "%", "digits": 0, "percent": true}],
  "qc": [{"scope": "sample", "expr": "CV", "max": 0.15, "msg": "CV {pct:.0f} % > 15 %"}],
  "reference_group": "К"
}
```

### Tubes and steps
- `per`: `series` means once per series (zero, blanks, controls, standards); `sample` means for every sample.
- `count`: how many such tubes. `{i}` in the label is the tube number; for standards `{x}` is the concentration.
- Exactly one tube type has `"zero": true`. It sets the zero of the instrument at **all** its wavelengths,
  so list every wavelength used anywhere in the protocol.
- Steps:
  - `{"do": "text"}`: the operator does something and presses Space.
  - `{"wait": seconds, "from": i, "text": "…"}`: a timer. `from` is the step it counts from (default:
    the previous step). The SOD protocol counts 10 min from the start (`from: 0`), not from A₀.
  - `{"read": "name", "wl": [nm, …]}`: a measurement. The values are named `name_<wl>`;
    with one wavelength, also plain `name`.

### Formulas
The order of calculation is: `series_calc` → `tube_calc` (for every tube) → `sample_calc` → `qc`.

Allowed in formulas:
- numbers and `+ − * / **`;
- comparisons and `a if condition else b`;
- functions `mean sd cv n sum min max first abs sqrt log10 ln exp`;
- `nz(x, 0)`, which turns a missing value into 0, and `has(x)`.

Names you can use:
- **Inside a tube**: its reads (`A0`, `fon_412`), constants, series variables and sample inputs.
  A sample tube also sees the measured values of the other tube types of the same sample,
  for example `mean(bg)` in catalase.
- **In a sample formula**: `test` is the list of measured values of that sample's `test` tubes;
  `test.C` is the list of the computed variable `C`. A list must be wrapped in `mean(...)` and similar.
- **In a series formula**: the same, over the series tubes: `mean(blank)`, `mean(control.dA)`.
- **Calibration**: `k_slope`, `k_intercept`, `k_quad`, `k_r2`, `k_amax` / `k_amin` (the largest and
  smallest A of the standards) and the function `k_conc(A)`, which gives x from A by the fitted curve of
  any model (`linear`, `origin`, `quadratic`). The prefix is set by `prefix`.

A value that has not been measured yet is empty (NaN); a result appears once its data exist.

### Quality checks
`qc`: `scope` is `series` or `sample`, `expr` is a formula, and `min` / `max` are the allowed limits.
In `msg`, `{v}` is the value and `{pct}` is the value × 100.
