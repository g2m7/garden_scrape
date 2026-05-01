import rich.console

original_print = rich.console.Console.print

def safe_print(self, *args, **kwargs):
    try:
        return original_print(self, *args, **kwargs)
    except UnicodeEncodeError:
        pass

rich.console.Console.print = safe_print
