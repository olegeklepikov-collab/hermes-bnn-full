from pathlib import Path
import json
from neutral_relocate import run
bundle=Path(__file__).resolve().parent
if (bundle/'Hermes/state/bootstrap.json').exists():raise PermissionError('Do not relocate an initialized owner profile')
old=Path(json.loads((bundle/'configuration/relocation.json').read_text())['build_root'])
print(run(bundle,old))
