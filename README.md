# Ofertas en seguridad, redes y tecnología

Página pública de precios. Se actualiza automáticamente cada día.

## Catálogo completo (catalogo.html)
Cada día (6:17 a.m.) una acción de GitHub descarga los productos con existencia
desde la API TVC Connect (api.tvc.mx) y publica `catalogo/` junto con el sitio.
Requiere el secreto `TVC_TOKEN` en Settings → Secrets and variables → Actions.
Margen opcional en Variables: `MARGEN` (por defecto 0.15). Precios con IVA.
También existe `tools/sync_syscom.py` por si después se conecta la API de Syscom.
