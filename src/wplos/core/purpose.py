from enum import StrEnum


class Purpose(StrEnum):
    """Why a mind is being asked, as a closed vocabulary.

    The same mind needs different context for different jobs: Radar looking for
    something local needs the city, her interests and when she is free, and has
    no business with cycle context. A free-text purpose cannot be checked
    against a policy, so purpose is typed and the scope it implies is declared.
    """

    PLAN_DAY = "PLAN_DAY"
    DIRECTION_CHECK = "DIRECTION_CHECK"
    CLOSE_OPEN_LOOPS = "CLOSE_OPEN_LOOPS"
    GET_READY = "GET_READY"
    FIND_LOCAL_EVENT = "FIND_LOCAL_EVENT"
    WELLNESS_OPPORTUNITY = "WELLNESS_OPPORTUNITY"
    CAPTURE_TRIAGE = "CAPTURE_TRIAGE"
    SAFETY_REVIEW = "SAFETY_REVIEW"
    EXECUTE_ACTION = "EXECUTE_ACTION"
    REFLECT = "REFLECT"
