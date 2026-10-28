"""Built-in protocols: oxidative stress markers in rat plasma (the lab's working scheme:
two Eppendorfs per animal) and two generic templates.

Formulas, volumes and quality checks follow the lab document
"Маркери оксидативного стресу в плазмі крові щура: МДА, СОД, каталаза, SH-групи/GSH"
and its Excel journal. Every protocol can be copied to SpecRec_data/protocols/ as JSON and
edited (see docs/PROTOCOLS.md).

"demo" gives the virtual instrument plausible absorbances (demo mode only).
"""
from __future__ import annotations

MDA = {
    "id": "mda", "name": "МДА (ТБК-активні продукти)", "version": 1,
    "source": "Стальна, Гарішвілі 1977; робоча схема: еппендорф 2, ½ масштабу, дублікати",
    "description": ("0,3 мл плазми + 0,3 мл 10 % ТХО → 10 хв 10 000 g → 0,45 мл супернатанту + 0,45 мл "
                    "0,8 % ТБК → кипляча баня 10 хв → лід 10 хв → A532 і A600 проти контролю "
                    "(вода замість плазми через увесь хід). Кювета зі звуженням (0,9 мл)."),
    "prep": [
        "Увімкнути водяну баню (має кипіти до кип'ятіння)",
        "0,8 % ТБК — свіжа, розчинена на бані 50–60 °C, тримати теплою",
        "10 % ТХО (+ за бажанням 6 мкл 2 % BHT на пробу)",
        "Контроль: 0,3 мл води замість плазми — через увесь хід",
        "Перевірити водою, що 0,9 мл у кюветі зі звуженням перекривають промінь",
        "Пробірки з фіксатором кришки або скляні з гвинтовою кришкою для кип'ятіння",
    ],
    "timers": [{"label": "Центрифуга (ТХО) 10 хв", "seconds": 600},
               {"label": "Кип'ятіння 10 хв", "seconds": 600},
               {"label": "Лід 10 хв", "seconds": 600}],
    "constants": {"dil": 4, "eps": 0.156},
    "tubes": {
        "zero": {"label": "Контроль (вода через увесь хід) — нуль приладу", "per": "series", "count": 1,
                 "zero": True, "steps": [{"read": "E", "wl": [532, 600]}]},
        "test": {"label": "Проба {i}", "per": "sample", "count": 2,
                 "steps": [{"read": "E", "wl": [532, 600]}]},
    },
    "tube_calc": {"test": {"Ek": "E_532 - E_600", "C": "Ek * dil / eps"}},
    "sample_calc": {"C": "mean(test.C) * dilution", "CV": "cv(test.C)", "Emin": "min(test.Ek)",
                    "Emax": "max(test.Ek)"},
    "inputs": {"dilution": {"label": "Розведення", "default": 1}},
    "results": [{"var": "C", "label": "МДА", "unit": "мкмоль/л", "digits": 2},
                {"var": "CV", "label": "CV дублікатів", "unit": "%", "digits": 0, "percent": True}],
    "qc": [
        {"scope": "sample", "expr": "Emin", "min": 0.02, "msg": "низький сигнал (E < 0,02)"},
        {"scope": "sample", "expr": "Emax", "max": 1.5, "msg": "E > 1,5 — розвести"},
        {"scope": "sample", "expr": "CV", "max": 0.15, "msg": "CV {pct:.0f} % > 15 % — повторити"},
    ],
    "demo": {"test": {"E_532": [0.08, 0.16], "E_600": [0.005, 0.015]}},
}

CATALASE = {
    "id": "catalase", "name": "Каталаза (молібдатний метод)", "version": 1,
    "source": "Королюк та співавт. 1988; оригінальний масштаб, 3,1 мл; еппендорф 1",
    "description": ("2,0 мл 0,03 % H₂O₂ + 0,1 мл плазми → рівно 10 хв → 1 мл 4 % молібдату → A410 проти "
                    "контролю реактивів. ΔE = Eхол − (Eдосл − Eфон); A = ΔE / (k·10 хв·0,1 мл) × розведення. "
                    "Пробірки запускати зі зсувом 30 с."),
    "prep": [
        "0,03 % H₂O₂ — свіжий (0,3 мл 3 % + 29,7 мл води); перевірка A240 ≈ 0,38 у кварцовій кюветі",
        "4 % молібдат амонію (мутний — вилити)",
        "Реактиви й плазма — кімнатної температури; записати температуру",
        "Калібрування H₂O₂ з тієї ж порції розчину",
        "Секундомір: кожна пробірка — свій відлік 10 хв, зсув 30 с",
    ],
    "stagger": 30,
    "timers": [],
    "constants": {"t_inc": 10, "V": 0.1},
    "calibration": {"type": "std", "x": [0, 4.41, 8.82, 13.2, 17.6], "unit": "мкмоль H₂O₂",
                    "model": "linear", "prefix": "k"},
    "tubes": {
        "zero": {"label": "Контроль реактивів (2,1 мл води + 1 мл молібдату) — нуль", "per": "series",
                 "count": 1, "zero": True, "steps": [{"read": "E", "wl": [410]}]},
        "std": {"label": "Калібрування: {x} мкмоль H₂O₂", "per": "series",
                "steps": [{"do": "H₂O₂ + вода до 2,1 мл, + 1 мл молібдату, перемішати"},
                          {"read": "E", "wl": [410]}]},
        "blank": {"label": "Холоста (без плазми)", "per": "series", "count": 2,
                  "steps": [{"do": "2,0 мл H₂O₂ + 0,1 мл води — старт відліку"},
                            {"wait": 600, "from": 0, "text": "інкубація 10 хв"},
                            {"do": "Додайте 1 мл молібдату, перемішайте"},
                            {"read": "E", "wl": [410]}]},
        "test": {"label": "Дослідна {i}", "per": "sample", "count": 2,
                 "steps": [{"do": "2,0 мл H₂O₂ + 0,1 мл плазми, перемішати — старт відліку"},
                           {"wait": 600, "from": 0, "text": "інкубація 10 хв"},
                           {"do": "Додайте 1 мл молібдату, перемішайте"},
                           {"read": "E", "wl": [410]}]},
        "bg": {"label": "Фон зразка", "per": "sample", "count": 1,
               "steps": [{"do": "2,0 мл води + 0,1 мл плазми + 1 мл молібдату"},
                         {"read": "E", "wl": [410]}]},
    },
    "series_calc": {"Ehol": "mean(blank)"},
    "tube_calc": {"test": {"dE": "Ehol - (E - mean(bg))", "A": "dE / (k_slope * t_inc * V) * dilution"}},
    "sample_calc": {"A": "mean(test.A)", "CV": "cv(test.A)", "mkat": "A * 16.67",
                    "lin": "(mean(test) - mean(bg)) / Ehol"},
    "inputs": {"dilution": {"label": "Розведення плазми", "default": 1}},
    "results": [{"var": "A", "label": "Каталаза", "unit": "мкмоль/хв/мл", "digits": 3},
                {"var": "mkat", "label": "Каталаза", "unit": "мккат/л", "digits": 1},
                {"var": "CV", "label": "CV дублікатів", "unit": "%", "digits": 0, "percent": True}],
    "qc": [
        {"scope": "series", "expr": "k_r2", "min": 0.99, "msg": "R² калібрування {v:.3f} < 0,99 — повторити"},
        {"scope": "sample", "expr": "lin", "min": 0.5,
         "msg": "(Eдосл − Eфон) < ½ Eхол — розвести плазму 1:2 (розведення = 2)"},
        {"scope": "sample", "expr": "CV", "max": 0.15, "msg": "CV {pct:.0f} % > 15 % — повторити"},
    ],
    "demo": {"std": {"E": "0.012 + 0.0415 * x"}, "blank": {"E": [0.70, 0.74]},
             "test": {"E": [0.40, 0.55]}, "bg": {"E": [0.03, 0.06]}},
}

SOD = {
    "id": "sod", "name": "СОД (НСТ / ФМС / НАДН)", "version": 1,
    "source": "Дубініна 1983 (екстракція), Чеварі 1985 (визначення); еппендорф 1, ½ екстракції",
    "description": ("Екстракт: 0,25 мл плазми + 0,125 мл етанол:хлороформ 5:3 + 10 мкл KH₂PO₄ → 10 хв 5000 g. "
                    "Проба: 2,0 мл Р1 + 0,05 мл екстракту (контроль — вода) + 0,1 мл Р2 — старт. "
                    "A₀ протягом 30 с, 10 хв у темряві, A₁₀ при 540 нм, нуль на воді. "
                    "Пробірки запускати зі зсувом 1 хв."),
    "prep": [
        "ФМС додати в Реагент 1 безпосередньо перед роботою; Р1 — кімнатної температури, у темряві",
        "Реагент 2 (1 мМ НАДН у трис-ЕДТА) — свіжий, на льоду; перевірка 1:20 → A340 ≈ 0,31",
        "Екстракт тримати на льоду, аналізувати того ж дня",
        "Темна коробка для інкубації",
        "Не залишати формазан у кюветах; кювети мити етанолом",
    ],
    "stagger": 60,
    "timers": [{"label": "Екстракція: 5 хв на льоду", "seconds": 300},
               {"label": "Центрифуга 10 хв", "seconds": 600}],
    "constants": {"V_ext": 0.05, "plasma_dil": 1.5},
    "tubes": {
        "zero": {"label": "Вода — нуль приладу", "per": "series", "count": 1, "zero": True,
                 "steps": [{"read": "A", "wl": [540]}]},
        "control": {"label": "Контроль К{i} (вода замість екстракту)", "per": "series", "count": 3,
                    "steps": [{"do": "2,0 мл Р1 + 0,05 мл води + 0,1 мл Р2, перемішати — СТАРТ"},
                              {"read": "A0", "wl": [540]},
                              {"wait": 600, "from": 0, "text": "10 хв у темряві"},
                              {"read": "A10", "wl": [540]}]},
        "test": {"label": "Дослідна {i}", "per": "sample", "count": 2,
                 "steps": [{"do": "2,0 мл Р1 + 0,05 мл екстракту + 0,1 мл Р2, перемішати — СТАРТ"},
                           {"read": "A0", "wl": [540]},
                           {"wait": 600, "from": 0, "text": "10 хв у темряві"},
                           {"read": "A10", "wl": [540]}]},
    },
    "tube_calc": {"control": {"dA": "A10 - A0"},
                  "test": {"dA": "A10 - A0", "T": "(dAk - dA) / dAk", "uo": "T / (1 - T)"}},
    "series_calc": {"dAk": "mean(control.dA)", "A0k": "mean(control.A0)"},
    "sample_calc": {"uo": "mean(test.uo)", "uo_ml": "uo / V_ext * plasma_dil * dilution",
                    "T": "mean(test.T)", "CV": "cv(test.uo)"},
    "inputs": {"dilution": {"label": "Розведення екстракту", "default": 1}},
    "results": [{"var": "uo_ml", "label": "СОД", "unit": "у.о./мл плазми", "digits": 2},
                {"var": "T", "label": "Інгібування T", "unit": "%", "digits": 0, "percent": True},
                {"var": "CV", "label": "CV дублікатів", "unit": "%", "digits": 0, "percent": True}],
    "qc": [
        {"scope": "series", "expr": "dAk", "min": 0.3, "max": 0.6,
         "msg": "ΔAк = {v:.3f} поза 0,3–0,6: підлаштувати ФМС / замінити НАДН (режим не міняти в серії)"},
        {"scope": "sample", "expr": "T", "max": 0.8, "msg": "T {pct:.0f} % > 80 % — розвести екстракт 1:2 (розведення = 2)"},
        {"scope": "sample", "expr": "T", "min": 0.2, "msg": "T {pct:.0f} % < 20 % — взяти 0,1 мл екстракту"},
        {"scope": "sample", "expr": "CV", "max": 0.15, "msg": "CV {pct:.0f} % > 15 % — повторити"},
    ],
    "demo": {"control": {"A0": [0.08, 0.10], "A10": [0.50, 0.56]},
             "test": {"A0": [0.08, 0.10], "A10": [0.25, 0.40]}},
}

SH = {
    "id": "sh", "name": "SH-групи (Елман) + гемоліз", "version": 1,
    "source": "Ellman 1959; Harboe з поправкою Аллена (вільний Hb); еппендорф 1",
    "description": ("0,95 мл буфера А + 0,05 мл плазми → Aфон при 412 нм і A380/A415/A450 (гемоліз) → "
                    "+ 0,02 мл 10 мМ ДТНБ, 15 хв у темряві → Aзр при 412 нм. Нуль — буфер А. "
                    "ΔA = Aзр − Aфон·1,00/1,02 − Aреаг; SH = ΔA / 0,01415 · 1,02 / 0,05."),
    "prep": [
        "Буфер А: 0,25 М трис-HCl, 1 мМ ЕДТА, pH 8,0",
        "10 мМ ДТНБ у буфері А, у фользі (яскраво-жовтий — вилити)",
        "Контроль методу: 0,5 мМ GSH — свіжий, використати протягом 1 год",
        "Кювета зі звуженням (1,02 мл)",
    ],
    "stagger": 30,
    "timers": [],
    "constants": {"eps": 0.01415, "V_before": 1.0, "V_after": 1.02, "V_plasma": 0.05},
    "tubes": {
        "zero": {"label": "Буфер А — нуль приладу", "per": "series", "count": 1, "zero": True,
                 "steps": [{"read": "A", "wl": [380, 412, 415, 450]}]},
        "reag": {"label": "Бланк реактиву (1,0 мл буфера А + 0,02 мл ДТНБ)", "per": "series", "count": 1,
                 "steps": [{"read": "A", "wl": [412]}]},
        "gsh": {"label": "Контроль GSH 0,5 мМ (замість плазми)", "per": "series", "count": 1,
                "steps": [{"read": "fon", "wl": [412]},
                          {"do": "Додайте 0,02 мл 10 мМ ДТНБ, перемішайте"},
                          {"wait": 900, "from": 1, "text": "15 хв у темряві"},
                          {"read": "zr", "wl": [412]}]},
        "test": {"label": "Проба {i}", "per": "sample", "count": 2,
                 "steps": [{"read": "fon", "wl": [380, 412, 415, 450]},
                           {"do": "Додайте 0,02 мл 10 мМ ДТНБ, перемішайте"},
                           {"wait": 900, "from": 1, "text": "15 хв у темряві"},
                           {"read": "zr", "wl": [412]}]},
    },
    "series_calc": {"Areag": "mean(reag)", "dA_gsh": "mean(gsh.dA)"},
    "tube_calc": {
        "gsh": {"dA": "zr - fon * V_before / V_after - nz(Areag)"},
        "test": {"dA": "zr - fon_412 * V_before / V_after - nz(Areag)",
                 "SH": "dA / eps * V_after / V_plasma",
                 "Hb": "max(0, 20 * (167.2 * fon_415 - 83.6 * fon_380 - 83.6 * fon_450))"},
    },
    "sample_calc": {"SH": "mean(test.SH) * dilution", "CV": "cv(test.SH)", "Hb": "first(test.Hb)"},
    "inputs": {"dilution": {"label": "Розведення", "default": 1}},
    "results": [{"var": "SH", "label": "SH-групи", "unit": "мкмоль/л", "digits": 0},
                {"var": "Hb", "label": "Вільний Hb", "unit": "мг/л", "digits": 0},
                {"var": "CV", "label": "CV дублікатів", "unit": "%", "digits": 0, "percent": True}],
    "qc": [
        {"scope": "series", "expr": "abs(dA_gsh - 0.35) / 0.35", "max": 0.15,
         "msg": "контроль GSH: ΔA відрізняється від 0,35 більш ніж на 15 % — перевірити ДТНБ / піпетки"},
        {"scope": "sample", "expr": "Hb", "max": 500, "msg": "виражений гемоліз (Hb {v:.0f} мг/л)"},
        {"scope": "sample", "expr": "Hb", "max": 100, "msg": "помірний гемоліз (Hb {v:.0f} мг/л)"},
        {"scope": "sample", "expr": "CV", "max": 0.15, "msg": "CV {pct:.0f} % > 15 % — повторити"},
    ],
    "demo": {"reag": {"A": [0.02, 0.03]},
             "gsh": {"fon": [0.0, 0.01], "zr": [0.37, 0.40]},
             "test": {"fon_412": [0.05, 0.09], "fon_380": [0.05, 0.08], "fon_415": [0.06, 0.10],
                      "fon_450": [0.03, 0.05], "zr": [0.30, 0.40]}},
}

ENDPOINT = {
    "id": "endpoint", "name": "Шаблон: кінцева точка (одна λ, множник)", "version": 1,
    "source": "загальний шаблон — скопіюйте й змініть під свою методику",
    "description": "Нуль на бланку, дві проби на зразок, результат = середнє A × множник × розведення.",
    "prep": ["Бланк — усі реактиви без зразка"],
    "timers": [],
    "constants": {"factor": 1.0},
    "tubes": {
        "zero": {"label": "Бланк — нуль приладу", "per": "series", "count": 1, "zero": True,
                 "steps": [{"read": "A", "wl": [540]}]},
        "test": {"label": "Проба {i}", "per": "sample", "count": 2, "steps": [{"read": "A", "wl": [540]}]},
    },
    "sample_calc": {"A": "mean(test)", "C": "A * factor * dilution", "CV": "cv(test)"},
    "inputs": {"dilution": {"label": "Розведення", "default": 1}},
    "results": [{"var": "A", "label": "A", "unit": "", "digits": 3},
                {"var": "C", "label": "Результат", "unit": "", "digits": 3},
                {"var": "CV", "label": "CV", "unit": "%", "digits": 0, "percent": True}],
    "qc": [{"scope": "sample", "expr": "CV", "max": 0.15, "msg": "CV {pct:.0f} % > 15 %"}],
    "demo": {"test": {"A": [0.2, 0.6]}},
}

CALIB = {
    "id": "calibration", "name": "Шаблон: калібрувальна крива + зразки", "version": 1,
    "source": "загальний шаблон — змініть стандарти (x), довжину хвилі, одиниці",
    "description": ("Стандарти з відомою концентрацією → пряма A = a + k·C; концентрація зразка "
                    "C = (A − a) / k × розведення."),
    "prep": ["Приготувати стандарти й бланк з тих самих реактивів"],
    "timers": [],
    "constants": {},
    "calibration": {"type": "std", "x": [0, 2, 5, 10, 20], "unit": "мкМ", "model": "linear", "prefix": "k"},
    "tubes": {
        "zero": {"label": "Бланк — нуль приладу", "per": "series", "count": 1, "zero": True,
                 "steps": [{"read": "A", "wl": [540]}]},
        "std": {"label": "Стандарт {x}", "per": "series", "steps": [{"read": "A", "wl": [540]}]},
        "test": {"label": "Проба {i}", "per": "sample", "count": 2, "steps": [{"read": "A", "wl": [540]}]},
    },
    "sample_calc": {"A": "mean(test)", "C": "(A - k_intercept) / k_slope * dilution", "CV": "cv(test)"},
    "inputs": {"dilution": {"label": "Розведення", "default": 1}},
    "results": [{"var": "C", "label": "Концентрація", "unit": "мкМ", "digits": 2},
                {"var": "A", "label": "A", "unit": "", "digits": 3},
                {"var": "CV", "label": "CV", "unit": "%", "digits": 0, "percent": True}],
    "qc": [{"scope": "series", "expr": "k_r2", "min": 0.99, "msg": "R² {v:.3f} < 0,99"},
           {"scope": "sample", "expr": "CV", "max": 0.15, "msg": "CV {pct:.0f} % > 15 %"}],
    "demo": {"std": {"A": "0.01 + 0.03 * x"}, "test": {"A": [0.1, 0.5]}},
}

BUILTIN = [MDA, CATALASE, SOD, SH, ENDPOINT, CALIB]
