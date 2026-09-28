# DisenoTransXBandas V1.0: Flat and V-Belt Drive Design.
# Belt Drive Design Tool

A desktop engineering application for the automated sizing and design of **V-belt** and **flat belt** power transmission systems, developed as a mechanical engineering capstone project at Universidad Industrial de Santander (Colombia).

The tool fills a real gap in commercial software: while V-belt design tools exist, no widely available desktop application handles **flat belt** sizing to ISO 22 / BS 3790 standards with catalog-driven output.

---

## Features

### V-Belt Design (BS 3790 / ISO 4184)
- Covers classical profiles: **A, B, C, D, E** and metric **SPZ, SPA, SPB, SPC**
- High-capacity profiles: **3V, 5V, 8V**
- Light-duty (FHP) profiles: **3L, 4L, 5L**
- Catalog and manual design modes
- Automatic belt selection from commercial catalog lengths
- Number-of-belts calculation with correction for contact angle and belt length

### Flat Belt Design (ISO 22)
- Catalog-driven width selection from ISO 22 standard series
- Euler–Eytelwein equation with centrifugal force correction
- Pulley correction factors per Shigley Table 17-4
- Metric and imperial width normalization

### Both Systems
- Power range: **1–700 HP** (0.75–522 kW)
- Speed range: **100–5,500 RPM**
- Transmission ratios: **1:1 to 7:1**
- Open and cross-belt configurations
- Metric and imperial unit systems (live switching)
- Machine service factor guide with 30+ machine types (double-click to apply)
- Shaft load calculation (resultant dynamic force on bearings)
- Taper bushing and keyway selection

### Output
- Detailed calculation memory with all intermediate values
- **Three engineering drawings** (transmission overview + driver pulley + driven pulley) generated as SVG and exported to PNG
- Drawing templates for solid disc, web, and spoked pulleys
- Commercial belt reference numbers (e.g., SPB-2240, B-75)

---

## Technical Architecture

The application follows a four-layer architecture:

```
┌─────────────────────────────────────────┐
│         interfaz_grafica.py             │  Tkinter GUI
│   (scrollable, resizable, unit switcher)│
├─────────────────────────────────────────┤
│  nucleo_diseno_correas.py               │  V-belt calculation engine
│  nucleo_diseno_planas.py                │  Flat belt calculation engine
├─────────────────────────────────────────┤
│         visualizacion_correas.py        │  SVG template rendering
│   (font metrics, token substitution,    │
│    dimension text re-centering)         │
├─────────────────────────────────────────┤
│         Excel Databases (.xlsx)         │  Belt catalogs, pulley specs,
│   (belt specs, ISO widths, correction   │  service factors, taper bushings
│    tables, commercial references)       │
└─────────────────────────────────────────┘
```

### Key Modules

| File | Lines | Role |
|------|-------|------|
| `nucleo_diseno_correas.py` | ~900 | V-belt design: profile selection, belt tensions (T₁, T₂, T₀), shaft load, SVG generation |
| `nucleo_diseno_planas.py` | 1,003 | Flat belt design: Euler–Eytelwein solver, ISO 22 width catalog, unit conversion |
| `visualizacion_correas.py` | 797 | SVG template substitution with font-metric-aware text centering (Arial, DejaVu, Century Gothic) |
| `interfaz_grafica.py` | 992 | Tkinter GUI with live unit switching, machine guide table, SVG→PNG rendering |

---

## Dependencies

```
python >= 3.9
numpy
pandas
scipy
Pillow (PIL)
cairosvg
tkinter  # included in standard Python on Windows/macOS
```

Install with:

```bash
pip install numpy pandas scipy Pillow cairosvg
```

---

## Design Standards

| Standard | Applies to |
|----------|-----------|
| **ISO 4184** | V-belt groove profiles and dimensions |
| **ISO 22** | Flat belt widths and tolerances |
| **BS 3790** | V-belt drive design method |
| **Shigley's MED** | Service factors, pulley correction factors (Tables 17-3, 17-4) |

---

## Validation

The design engine was validated against **10 independent case studies** drawn from:
- *Shigley's Mechanical Engineering Design* (Budynas & Nisbett)
- Manufacturer application guides (Gates, Optibelt)

All results matched to within acceptable engineering tolerance for catalog-driven design.

---

## Background

This project was developed as the author's mechanical engineering degree project at **Universidad Industrial de Santander**, Bucaramanga, Colombia. The motivation was the absence of any open-source or freely available tool capable of designing both flat belt and V-belt transmissions from the same interface, covering the full commercial catalog and producing dimensioned engineering drawings automatically.

The thermodynamic analysis module referenced in the paper (multi-stage steam cycle with biomass combustion) is a separate project available in this repository under `thermo/`.

---

## Author

**Gerardo Alarcon Baldovino**  
Mechanical Engineering — Universidad Industrial de Santander  
[LinkedIn](https://linkedin.com/in/gerardo-alarcon) · gerardoalarconila@gmail.com

---

## License

MIT License — free to use, modify, and distribute with attribution.
