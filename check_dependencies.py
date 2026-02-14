#!/usr/bin/env python
"""Check if qualitative voice dependencies are installed."""

import sys

print("=" * 60)
print("Qualitative Voice Metrics - Dependency Check")
print("=" * 60)
print(f"Python: {sys.version}")
print()

deps = [
    ("torch", "torch", "Deep learning framework for ML models"),
    ("transformers", "transformers", "Hugging Face models for emotion detection"),
    ("speechbrain", "speechbrain", "Speaker consistency (ECAPA-TDNN)"),
    ("librosa", "librosa", "Audio loading and processing"),
    ("parselmouth", "parselmouth", "Prosody and acoustic metrics (Praat)"),
    ("scipy", "scipy", "Scientific computing"),
]

all_installed = True

for name, module, description in deps:
    try:
        m = __import__(module)
        version = getattr(m, "__version__", "installed")
        print(f"✅ {name}: {version}")
        print(f"   └─ {description}")
    except ImportError as e:
        all_installed = False
        print(f"❌ {name}: NOT INSTALLED")
        print(f"   └─ {description}")
        print(f"   └─ Error: {e}")
    except Exception as e:
        all_installed = False
        print(f"⚠️  {name}: IMPORT ERROR (version conflict?)")
        print(f"   └─ {description}")
        print(f"   └─ Error: {e}")
    print()

print("=" * 60)
if all_installed:
    print("✅ All dependencies installed! Qualitative metrics should work.")
else:
    print("❌ Some dependencies are missing!")
    print()
    print("Install with:")
    print('  pip install torch transformers speechbrain librosa praat-parselmouth scipy')
    print()
    print("Or install the optional group:")
    print('  pip install -e ".[qualitative-voice]"')
print("=" * 60)
