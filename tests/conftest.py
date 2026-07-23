import os
import sys

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)                                   # for `import ai...`
sys.path.insert(0, os.path.join(ROOT, "app", "backend"))   # for backend `import db/main`
