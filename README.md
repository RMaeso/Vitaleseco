# Constantes vitales · Economía española

Una página que resume la salud de la economía española con gráficos que se actualizan solos, al estilo de [Econvitals](https://econvitals.org/) de Jason Furman. Cada indicador compara España con la eurozona.

**Bloques:** crecimiento · empleo · inflación · condiciones financieras · vivienda · sector exterior · cuentas públicas (24 indicadores, 45 series).

## Cómo funciona

```
indicators.json          ← catálogo: qué series se descargan y de dónde
scripts/fetch_data.py    ← descarga Eurostat + BCE y genera site/data/data.json
site/                    ← la web (HTML + CSS + JS, sin dependencias)
.github/workflows/       ← GitHub Actions: descarga 2 veces al día y publica en GitHub Pages
tests/                   ← pruebas sin red del script
```

No hace falta servidor ni base de datos: GitHub ejecuta el script, guarda el `data.json` en el repositorio y publica la carpeta `site/` como web estática. Es gratis.

## Puesta en marcha (10 minutos)

1. Crea una cuenta en GitHub si no la tienes y un repositorio nuevo (público), por ejemplo `constantes-vitales`.
2. Sube todo el contenido de esta carpeta al repositorio (botón *Add file → Upload files*, arrastrando los archivos). Ojo: la carpeta `.github` está oculta en Mac y Windows; si no se sube, créala con *Add file → Create new file*, escribiendo como nombre `.github/workflows/actualizar.yml` y pegando su contenido.
3. En el repositorio: **Settings → Pages → Build and deployment → Source: GitHub Actions**.
4. La primera ejecución automática puede fallar en el paso de publicar si Pages aún no estaba activado; es normal. En **Actions**, abre «Actualizar datos y publicar» y pulsa **Run workflow**.
5. En 2-3 minutos la web estará en `https://TU-USUARIO.github.io/constantes-vitales/`.

A partir de ahí se actualiza sola a las 06:23 y 13:23 UTC.

## La primera ejecución: revisa las series

Las APIs de Eurostat y el BCE cambian códigos de vez en cuando (por ejemplo, el IPCA pasó a ECOICOP 2 en febrero de 2026 y la eurozona incorporó a Bulgaria en 2026). Por eso:

- Cada serie puede tener **fuentes alternativas**; si la primera falla se prueba la siguiente. Para la eurozona en Eurostat se prueban `EA`, `EA21` y `EA20`.
- Si una serie falla del todo, la web conserva el último dato bueno y lo marca como «sin actualizar».
- El registro de la ejecución (pestaña Actions) y el final de la propia web listan las series con error y el motivo. Cuando Eurostat responde que una dimensión tiene varios valores, el mensaje sugiere qué filtro añadir.

Para corregir una serie, edita su entrada en `indicators.json`. Puedes comprobar los códigos en el [navegador de datos de Eurostat](https://ec.europa.eu/eurostat/databrowser/) y en el [portal de datos del BCE](https://data.ecb.europa.eu/).

## Añadir un indicador

Copia un bloque de `indicators.json` y cambia los filtros. Tipos de fuente:

```json
{"type": "eurostat", "dataset": "une_rt_m", "filters": {"age": "TOTAL", "sex": "T", "s_adj": "SA", "unit": "PC_ACT"}}
{"type": "ecb", "flow": "ICP", "key": "M.ES.N.000000.4.ANR"}
```

Opciones por indicador: `unit`, `decimals`, `zero_line`, `target` (línea discontinua), `baseline`, `headline` (aparece en el resumen superior). Por serie: `transform: "yoy"` (variación interanual a partir de niveles) y `derive` (diferencia entre dos series, como la prima de riesgo).

## Probar en tu ordenador

```bash
python scripts/fetch_data.py         # descarga datos reales
python -m http.server -d site 8000   # abre http://localhost:8000
python -m unittest discover tests    # pruebas
```

## Ideas para la siguiente versión

- Datos que solo publica el INE o el Gobierno: afiliación a la Seguridad Social, paro registrado, compraventas de viviendas y hipotecas firmadas (API JSON del INE: `servicios.ine.es/wstempus`).
- Previsiones (Banco de España, AIReF, Comisión Europea) junto al último dato.
- Un breve texto de lectura de la situación, escrito a mano, encima del resumen.
- Dominio propio: *Settings → Pages → Custom domain*.

Fuentes: Eurostat y Banco Central Europeo (reutilización libre con cita de la fuente).
