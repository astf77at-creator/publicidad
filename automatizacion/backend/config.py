"""Configuración cargada desde variables de entorno (.env)."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Odoo
    odoo_url: str = ""
    odoo_db: str = ""
    odoo_username: str = ""
    odoo_api_key: str = ""
    odoo_category_field: str = "categ_id"
    odoo_brand_field: str = "product_brand_id"
    odoo_reference_field: str = "default_code"
    odoo_published_field: str = "is_published"
    odoo_tag_review: str = "Revisión de imágenes"
    # Color de la etiqueta de revisión. El widget de Odoo pinta por ÍNDICE de
    # paleta (no hex): 1=rojo, 2=naranja, 3=amarillo, 10=verde… Igual que las
    # etiquetas WC (Listo="3", Publicado="10"). 2 = naranja para que destaque.
    odoo_tag_review_color: str = "2"
    odoo_tag_ready: str = "Listo"
    # Campo del PIN de empleado usado para autenticar (mismo que el lanzador).
    odoo_pin_field: str = "yh_checador_pin"

    # Conexión SEPARADA para validar el PIN (auth). Útil cuando los productos
    # viven en producción (sin el campo del PIN) pero los empleados/PINs del
    # lanzador están en otra instancia (el espejo). Si se dejan vacías, la auth
    # usa la misma conexión principal (odoo_url/db/...).
    odoo_auth_url: str = ""
    odoo_auth_db: str = ""
    odoo_auth_username: str = ""
    odoo_auth_api_key: str = ""

    # OpenAI
    openai_api_key: str = ""
    openai_image_model: str = "gpt-image-1"
    poses_por_producto: int = 6

    # Cola de trabajos: cuántas generaciones se procesan EN PARALELO. Súbelo
    # con cuidado (cada una consume CPU/RAM y cuota de OpenAI). 2 es seguro.
    concurrencia_jobs: int = 2

    # Imágenes de salida
    img_ancho: int = 800
    img_alto: int = 1000
    img_max_kb: int = 100

    # Servidor
    host: str = "0.0.0.0"
    port: int = 8080


settings = Settings()
