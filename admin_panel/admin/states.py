from aiogram.fsm.state import StatesGroup, State

async def tryFinish(state):
    try:
        await state.clear()
    except:
        pass

class AdminState(StatesGroup):
    State = State()