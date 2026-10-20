def get_refer_id(command_args):
    try:
        return int(command_args)
    except (TypeError, ValueError):
        return None