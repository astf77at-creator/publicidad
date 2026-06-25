"""Prompts por tipo de prenda para la API de imágenes.

Resumen de prompts-fotografia.md adaptado a la API: una pose por imagen.
La prenda es la protagonista (70-80% del encuadre); el rostro es secundario.
"""

REGLA_MAESTRA = (
    "La prenda es la protagonista y debe ocupar el 70-80% del encuadre. "
    "Acerca el plano y recorta lo necesario para que la prenda llene el cuadro. "
    "Minimiza el fondo vacío. La modelo y la cara son secundarias; el rostro "
    "puede quedar recortado o parcial. Fondo de estudio neutro gris claro "
    "minimalista, luz suave y sombra natural, estilo editorial comercial tipo Zara. "
    "No agregues texto, marcas de agua, marcos ni elementos gráficos."
)

# Uniformidad: todas las poses del MISMO producto deben verse como una sola
# sesión de fotos (misma modelo, mismo calzado, mismos colores). Sin esto, cada
# generación independiente inventa zapatos/tenis y colores distintos.
CONSISTENCIA = (
    "MUY IMPORTANTE — uniformidad de sesión: la imagen debe verse como parte de "
    "una sola sesión de fotos, con la MISMA modelo (mismo rostro, peinado, tono "
    "de piel y maquillaje), el MISMO calzado, el MISMO styling y los MISMOS "
    "colores y acabados que el resto de la serie. Respeta EXACTAMENTE el color, "
    "el tono y el estampado de la prenda de la referencia; no los cambies ni "
    "inventes otros. Usa un calzado neutro y sobrio coherente en todas las tomas."
)

# Se añade cuando se pasa una imagen ANCLA (la primera pose ya generada) como
# referencia extra: fuerza a copiar modelo, calzado, styling y colores de ella.
ANCLA = (
    "La última imagen de referencia es una toma PREVIA de esta misma sesión: "
    "replica idénticamente a esa misma modelo, su calzado, su styling y todos "
    "sus colores; lo único que cambia es la pose y el encuadre indicado."
)

# Contexto de decoro para evitar falsos positivos de moderación (p. ej. un body
# o traje de baño que el filtro confunde con ropa interior / contenido sexual).
DECORO = (
    "Contexto: es una fotografía de catálogo de MODA COMERCIAL para una tienda "
    "de ropa (e-commerce), totalmente decorosa, profesional y NO sugerente. La "
    "modelo lleva la prenda de forma apropiada y con cobertura adecuada. Si la "
    "prenda es un body, maillot, traje de baño u otra prenda ajustada de una "
    "pieza, estilízala como TOP combinándola con jeans o pantalón de tiro alto, "
    "como un conjunto de calle. No generes ropa interior, desnudos ni contenido "
    "sugerente: es una imagen de producto de moda apta para catálogo."
)

# Para cada tipo: el encuadre base + la lista de poses (una imagen por pose).
TIPOS: dict[str, dict] = {
    "superior": {
        "label": "Superior (blusa, camisa, top, sweater)",
        "encuadre": "Plano cerrado de torso, de hombros/cuello a la cadera. NO cuerpo completo.",
        "poses": [
            "frontal con manos relajadas",
            "tres cuartos con una mano hacia el rostro",
            "tres cuartos con mano en el bolsillo",
            "brazos cruzados",
            "perfil",
            "detalle de torso de pecho a cadera sin rostro, enfocado en tela y botones",
            "vuelta parcial de espalda mostrando el corte trasero",
            "tres cuartos trasero con giro de hombros",
        ],
    },
    "inferior": {
        "label": "Inferior (pantalón, jean, falda, short)",
        "encuadre": "Plano cerrado de la mitad inferior: de la cintura a los tobillos. Recorta por encima de la cintura.",
        "poses": [
            "frontal cintura a pies",
            "caminando",
            "perfil mostrando la caída",
            "tres cuartos",
            "sentada mostrando la pierna",
            "detalle de cintura y bolsillo",
            "trasero mostrando el ajuste y los bolsillos traseros",
            "detalle del bajo y la caída sobre el calzado",
        ],
    },
    "completo": {
        "label": "Abrigo, blazer, vestido, mono, conjunto",
        "encuadre": "Plano medio-largo cerrado: de la cabeza/hombros hasta justo bajo el bajo de la prenda. La prenda domina el cuadro. Evita el plano entero con la modelo pequeña.",
        "poses": [
            "frontal",
            "perfil",
            "caminando",
            "tres cuartos con mano en bolsillo",
            "sentada",
            "vuelta parcial de espalda",
            "tres cuartos frontal con movimiento de tela",
            "detalle de cuello y solapa o escote",
        ],
    },
    "calzado": {
        "label": "Calzado (zapatos, botas, sandalias, tenis)",
        "encuadre": "Plano cerrado de pies y tobillos, de la rodilla hacia abajo, el zapato grande y nítido.",
        "poses": [
            "detalle frontal de pies",
            "detalle de perfil",
            "paso cruzado",
            "caminando",
            "de pie",
            "toma de contexto de styling",
            "detalle cenital desde arriba",
            "par de pies juntos de frente",
        ],
    },
    "accesorio": {
        "label": "Accesorio (bolso, cinturón, gafas, joyería)",
        "encuadre": "Plano de detalle cerrado con el accesorio grande y nítido; el cuerpo solo como apoyo.",
        "poses": [
            "detalle frontal",
            "detalle en ángulo",
            "llevado puesto en plano medio",
            "en mano",
            "caminando con el accesorio visible",
            "primerísimo plano de textura y material",
            "tres cuartos llevado puesto",
            "vista trasera o del cierre/broche",
        ],
    },
}


def build_prompt(tipo: str, descripcion: str, pose: str, anchor: bool = False) -> str:
    cfg = TIPOS.get(tipo, TIPOS["completo"])
    extra = (" " + ANCLA) if anchor else ""
    return (
        f"Usa la imagen subida ÚNICAMENTE como referencia de la prenda: {descripcion}. "
        f"Genera UNA imagen en esta pose: {pose}. "
        f"Reproduce la prenda con fidelidad total en color, patrón, textura, proporción "
        f"y detalles. {cfg['encuadre']} {REGLA_MAESTRA} {CONSISTENCIA} {DECORO}{extra}"
    )


def poses_for(tipo: str, n: int) -> list[str]:
    poses = TIPOS.get(tipo, TIPOS["completo"])["poses"]
    return (poses * ((n // len(poses)) + 1))[:n]
