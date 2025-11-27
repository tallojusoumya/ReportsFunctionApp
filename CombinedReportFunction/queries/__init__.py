"""Query definitions organized by table"""

from .database_salehead import QUERIES as SALEHEAD_QUERIES
from .database_purchasehead import QUERIES as PURCHASEHEAD_QUERIES
from .database_b2csalehead import QUERIES as B2CSALEHEAD_QUERIES
from .database_salereturnhead import QUERIES as SALERETURNHEAD_QUERIES
from .database_purchasereturnhead import QUERIES as PURCHASERETURNHEAD_QUERIES
from .database_expiry_inhead import QUERIES as EXPIRY_INHEAD_QUERIES
from .database_expiryouthead import QUERIES as EXPIRYOUTHEAD_QUERIES
from .database_transferinhead import QUERIES as TRANSFERINHEAD_QUERIES
from .database_transferouthead import QUERIES as TRANSFEROUTHEAD_QUERIES

# Combined queries dictionary
TABLES = {
    "Database_salehead": SALEHEAD_QUERIES,
    "Database_Purchasehead": PURCHASEHEAD_QUERIES,
    "Database_b2csalehead": B2CSALEHEAD_QUERIES,
    "Database_Salereturnhead": SALERETURNHEAD_QUERIES,
    "Database_Purchasereturnhead": PURCHASERETURNHEAD_QUERIES,
    "Database_Expiry_inhead": EXPIRY_INHEAD_QUERIES,
    "Database_Expiryouthead": EXPIRYOUTHEAD_QUERIES,
    "Database_Transferinhead": TRANSFERINHEAD_QUERIES,
    "Database_Transferouthead": TRANSFEROUTHEAD_QUERIES,
}

