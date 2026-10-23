"""The 30 priced lines of the workbook (rows 78 to 121), in workbook order.

qty_cell: workbook cell holding the quantity (rule cell, alias, or None for fixed).
fixed_qty: typed quantity in the workbook (not a formula). Business meaning unconfirmed.
label: workbook text verbatim. Several labels embed hardcoded counts and sizes that do not
follow the inputs (flagged, not corrected). role: steel role key for the five steel lines.
price: workbook unit price (default; later seeded from data).
"""
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class LineDef:
    row: int
    label: str
    unit: str
    price: float
    category: str
    qty_cell: Optional[str] = None
    fixed_qty: Optional[float] = None
    role: Optional[str] = None
    total_is_price: bool = False  # PPA line: quantity is text, total = price


STEEL, ROOF, WALL, ACCESSORY, SERVICE, EXTRA = (
    "acero", "techo", "paredes", "accesorios", "servicios", "extras",
)

LINES = [
    LineDef(78, "Suministro y fabricacion de 12 Columnas en vigas W 12¨X 8 X 42 lb", "Lb", 85, STEEL, "E42", role="columnas"),
    LineDef(79, "Suministro y fabricacion de 10 Vigas para porticos de frenado W 10 X 12 lb", "Lb", 85, STEEL, "E55", role="frenado"),
    LineDef(80, "Suministro y fabricacion de 6 Porticos en vigas de W 16¨x 26 lb", "Lb", 85, STEEL, "E51", role="tijerillas"),
    LineDef(81, "Suministro y fabricacion de columnas frontales", "Lb", 85, STEEL, "E47", role="frontales"),
    LineDef(82, "Suministro y fabricacion de Conexiones", "Lb", 85, STEEL, "E58", role="conexiones"),
    LineDef(83, "Suministro de tornillos de 3/4", "Unidad", 85, STEEL, "E64"),
    LineDef(84, "Fabricacion e instalcion  de pernos de 1¨", "Unidad", 5000, STEEL, "E62"),
    LineDef(88, "Suministro y colocacion de Aluzinc PPGl Cal. 26", "PIE", 195, ROOF, "C88"),
    LineDef(89, "Suministro y colocacion de correas Z de 8¨ cal. 1/16", "PIE", 175, ROOF, "E21"),
    LineDef(90, "Suministro y colocacion de planchas Translúcidas", "Unidad", 2500, ROOF, fixed_qty=10),
    LineDef(91, "Suministro e instalcion de tillas de 1/2", "Unidad", 250, ROOF, "E24"),
    LineDef(92, "Suministro de Tonilllos 1/2 para correas", "Unidad", 12, ROOF, "E25"),
    LineDef(93, "Suministro y tornillos de techo autoperforantes", "Unidad", 6, ROOF, "C93"),
    LineDef(94, "Suministro y fabricacion de riostras de 3/4", "Unidad", 1600, ROOF, fixed_qty=6),
    LineDef(95, "20 Tubos galvanizados 4 x 4 x 3.2 mm", "Unidad", 3200, ROOF, fixed_qty=20),
    LineDef(99, "Suministro y colocacion de Aluzinc Narural Cal. 26", "PIE", 185, WALL, "C99"),
    LineDef(100, "Suministro y colocacion de correas Z de 8¨ cal. 1/16", "PIE", 175, WALL, "C100"),
    LineDef(101, "Suministro e instalcion de tillas de 1/2", "Unidad", 250, WALL, "C101"),
    LineDef(102, "Suministro de Tonilllos 1/2 para correas", "Unidad", 12, WALL, "C102"),
    LineDef(103, "Suministro y tornillos de techo autoperforantes", "Unidad", 6, WALL, "C103"),
    LineDef(104, "Suministro y fabricacion de riostras de 3/4", "Unidad", 1600, WALL, fixed_qty=6),
    LineDef(107, "Suministro y colocacion de Caballete de 24”x 10 pie", "PIE", 270, ACCESSORY, "E28"),
    LineDef(108, "Suministro y colocacion de Caños de 24”x 10 pie", "PIE", 270, ACCESSORY, "E27"),
    LineDef(109, "Suministro y colocacion de Cubre falta  de 24” x 10 pies", "PIE", 270, ACCESSORY, "E29"),
    LineDef(110, "Suministro de Bajantes  de 4”", "Unidad", 3000, ACCESSORY, "E30"),
    LineDef(111, "Suministro de Boquillas de 4”", "Unidad", 400, ACCESSORY, "E31"),
    LineDef(115, "Servicio de transporte", "Colas", 30000, SERVICE, fixed_qty=1),
    LineDef(116, "Servicio de Grua", "Unidad", 18000, SERVICE, fixed_qty=35),
    LineDef(120, "Alojamientos", "unidad", 150000, EXTRA, total_is_price=True),
    LineDef(121, "Uniformes", "unidad", 50000, EXTRA, fixed_qty=1),
]

assert len(LINES) == 30
