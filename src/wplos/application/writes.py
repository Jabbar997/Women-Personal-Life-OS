from pydantic import BaseModel, ConfigDict

from wplos.agents.contracts import GraphWriteIntent
from wplos.core.roles import AgentName


class SanctionedWrite(BaseModel):
    """A write a mind asked for, after its contract was checked.

    The pairing is the point: an intent on its own has no author, and the
    application refuses to persist a change without knowing which mind asked and
    whether that mind was allowed to. It carries the intent unchanged — a mind's
    request is evidence, not something the runtime rewrites on its way past.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    agent: AgentName
    intent: GraphWriteIntent
