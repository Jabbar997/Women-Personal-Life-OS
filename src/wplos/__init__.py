"""Women Personal Life OS — domain foundation.

Layering (a module may only import from layers above it):

    shared -> core -> policy -> personal_life_graph -> events -> agents -> orchestration

Nothing in this package may import an LLM provider SDK. AI proposes, rules
constrain, policies authorize, the Operator executes.
"""

__version__ = "0.1.0"
