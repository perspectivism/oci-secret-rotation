import sys
from pathlib import Path

# Add function/ to sys.path so tests can import rotation, vault_client, target_client
# without installing the package.
sys.path.insert(0, str(Path(__file__).parent.parent))
