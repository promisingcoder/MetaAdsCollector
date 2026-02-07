"""Allow running the package directly: python -m meta_ads_collector"""

import sys

from .cli import main

sys.exit(main())
