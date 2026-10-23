# Diagramas de arquitectura

`arquitectura-aplicacion.svg` muestra solicitudes, autenticación, autorización, herramientas y datos. `arquitectura-operacion.svg` muestra controles transversales, costos y dependencias de Terraform. Los SVG son autónomos: incorporan los vectores de los íconos, no dependen de una CDN ni contienen scripts o recursos externos. Se pueden abrir desde el README para ampliar sin perder resolución.

## Fuente de los íconos

Los íconos de `aws-icons/` provienen del paquete oficial **AWS Architecture Icons, 31 de julio de 2026**. Se conservaron los SVG originales de los servicios utilizados. Son marcas y material gráfico de Amazon Web Services; su inclusión identifica componentes de la arquitectura, no implica patrocinio de AWS.

- [Página oficial y condiciones de uso de AWS Architecture Icons](https://aws.amazon.com/architecture/icons/).
- [Paquete oficial utilizado](https://d1.awsstatic.com/onedam/marketing-channels/website/public/shared/architecture-icon-release/Icon-package_07312026.5846e92413caa21490223536cc97f1269e44fa92.zip).
- SHA256 del ZIP: `d2d166c453526471749d520e0db022c459abef759d2946cf2dd1d1c992dc6526`.

La extracción conserva únicamente los 15 íconos de servicios usados por estos diagramas. No se requiere descargar el ZIP para regenerarlos.

## Regeneración

Desde la raíz del repositorio, con el Python del proyecto y sin dependencias adicionales:

```powershell
python scripts/render_architecture.py
```

La fuente editable es `scripts/render_architecture.py`; relaciona los componentes declarados en Terraform y el recorrido implementado en Python. Tras modificarla, regenerar ambos SVG y revisar visualmente etiquetas, flechas y límites. No representa servicios que no estén desplegados, ni una VPC implícita para los servicios administrados.
