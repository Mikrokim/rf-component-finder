# Vendor Lists

## ALWAYS EXCLUDE — the user's 12 pre-checked sites

The user checks these manually before every search. Pass all of them in `blocked_domains` on every web search, and never present parts from them:

| Vendor | Domain |
|---|---|
| Mini-Circuits | minicircuits.com |
| Qorvo (incl. Custom MMIC, Sirenza legacy parts) | qorvo.com |
| MACOM (incl. Mimix legacy) | macom.com |
| Analog Devices (incl. Hittite legacy) | analog.com |
| UMS | ums-rf.com |
| 3R Waves | 3rwave.com |
| AMCOM | amcomusa.com |
| VectraWave | vectrawave.com |
| Guerrilla RF | guerrilla-rf.com |
| Microchip | microchip.com |
| Marki Microwave | markimicrowave.com |
| RW MMIC | rwmmic.com |

Legacy-brand note: parts whose datasheets now live on an excluded domain (e.g. Custom MMIC → qorvo.com, Hittite → analog.com) count as excluded.

## SWEEP LIST — manufacturers to check directly

Generic web search misses many of these (poor indexing). For the relevant component category, check catalogs/site search directly. Not every vendor is relevant to every part type — use the category hints.

### MMIC / semiconductor
- Altum RF — altumrf.com (amps, X-Ku-band; also stocked at rellpower.com)
- BeRex — berex.com (amps, LNAs)
- CEL (California Eastern Labs) — cel.com (LNAs, discrete)
- Skyworks — skyworksinc.com (amps < ~6 GHz, switches, mixers)
- NXP — nxp.com (power, drivers)
- Wolfspeed — wolfspeed.com (GaN power)
- Ampleon — ampleon.com (power)
- Broadcom/Avago legacy MMICs — broadcom.com
- WIN Semiconductors (foundry parts via partners)
- OMMIC / MACOM Europe legacy — check via everything.rf
- Mercury Systems / Atlanta Micro — mrcy.com (AM-series amps)

### Connectorized modules / hybrid amplifiers
- Ciao Wireless — ciaowireless.com (very broad amp catalog, catalog PDFs parse well)
- Narda-MITEQ (L3Harris) — nardamiteq.com (huge AMF amplifier catalog — poorly indexed, sweep directly)
- Erzia — erzia.com
- B&Z Technologies — bnztech.com
- Planar Monolithics Industries (PMI) — pmi-rf.com
- Cernex / CernexWave — cernex.com
- Wenteq Microwave — wenteq.com (store.wenteq.com has per-part pages)
- Pasternack — pasternack.com (site bot-blocked; datasheets mirrored at resources.ampheo.com/static/datasheets/pasternack/<part>.pdf)
- Fairview Microwave — fairviewmicrowave.com
- Lotus Communication Systems — lotussys.com
- AML — amlj.com
- Elite RF — eliterfllc.com
- Triad RF — triadrf.com
- Spacek Labs — spaceklabs.com (mm-wave)
- Quantic brands (X-Microwave, PMI, Corry...) — check via catalog.xmicrowave.com

### Parametric search engines / distributors (search these too, not just Google)
- everything.rf — best RF-specific parametric DB; also mirrors specs of poorly-indexed vendors
- Mouser, Digi-Key — parametric filters for SMT/MMIC parts
- RFMW — rfmw.com — RF-specialist distributor
- Richardson Electronics — rellpower.com (Altum RF and others)

## Maintenance

When the user mentions a vendor not listed here, add it to the appropriate section. This file is the accumulated institutional knowledge of the search — it should grow.
