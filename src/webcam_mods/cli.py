"""Share Typer's validated options across root and command contexts."""

from copy import copy
from typing import Any, Callable, cast

from typer._click import Context
from typer.core import TyperCommand, TyperGroup, TyperOption


class SharedOptionsCommand(TyperCommand):
    shared_options_added = False

    def invoke(self, ctx: Context) -> Any:
        parent = ctx.parent
        if parent is None or not isinstance(parent.command, SharedOptionsGroup):
            raise RuntimeError("shared options require the root CLI context")
        options = dict(parent.params)
        for parameter in parent.command.params:
            if not isinstance(parameter, TyperOption):
                continue
            if (
                parameter.is_eager
                or not parameter.expose_value
                or parameter.name is None
            ):
                continue
            value = ctx.params.pop(parameter.name)
            source = ctx.get_parameter_source(parameter.name)
            if source is not None and source.name == "COMMANDLINE":
                options[parameter.name] = value
        # resolve once, after both positions have been parsed and before acquisition
        parent.invoke(parent.command.resolve_settings, **options)
        ctx.obj = parent.obj
        return super().invoke(ctx)


class SharedOptionsGroup(TyperGroup):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.resolve_settings = cast(Callable[..., Any], self.callback)
        self.callback = None

    def get_command(self, ctx: Context, cmd_name: str) -> SharedOptionsCommand | None:
        command = super().get_command(ctx, cmd_name)
        if command is None:
            return None
        if not isinstance(command, SharedOptionsCommand):
            raise TypeError("CLI commands must support shared options")
        if not command.shared_options_added:
            for parameter in self.params:
                if not isinstance(parameter, TyperOption):
                    continue
                if (
                    parameter.is_eager
                    or not parameter.expose_value
                    or parameter.name is None
                ):
                    continue
                option = copy(parameter)
                option.hidden = False
                command.params.append(option)
            command.shared_options_added = True
        return command
