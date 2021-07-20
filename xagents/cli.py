import argparse
import sys
import warnings

import pandas as pd

import xagents
from xagents.base import OffPolicy
from xagents.utils.cli import agent_args, non_agent_args, off_policy_args
from xagents.utils.common import create_buffers, create_envs, create_models


class Executor:
    """
    Command line parser.
    """

    def __init__(self):
        """
        Initialize supported commands and agents.
        """
        self.agent_id = None
        self.command = None
        self.agent = None

    @staticmethod
    def display_section(title, cli_args):
        """
        Display given title (command) and respective available options.
        Args:
            title: Command(s) that will be displayed on top of cli options.
            cli_args: A dictionary having flags and their respective
                `help`, `required` and `default`

        Returns:
            None
        """
        section_frame = pd.DataFrame(cli_args).T.fillna('-')
        section_frame['flags'] = section_frame.index.values
        section_frame['flags'] = section_frame['flags'].apply(lambda flag: f'--{flag}')
        section_frame = section_frame.reset_index(drop=True).set_index('flags')
        print(f'\n{title}\n')
        print(
            section_frame[
                [
                    column_name
                    for column_name in ('help', 'required', 'default')
                    if column_name in section_frame.columns
                ]
            ].to_markdown()
        )

    def display_commands(self, sections=None):
        """
        Display available commands and their description
            + command specific sections if given any.
        Args:
            sections: A dictionary having flags and their respective
                `help`, `required` and `default`

        Returns:
            None
        """
        print(f'xagents {xagents.__version__}')
        print(f'\nUsage:')
        print(f'\txagents <command> <agent> [options] [args]')
        print(f'\nAvailable commands:')
        for command, items in xagents.commands.items():
            print(f'\t{command:<10} {items[2]}')
        print()
        print('Use xagents <command> to see more info about a command')
        print('Use xagents <command> <agent> to see more info about command + agent')
        if sections:
            for title, cli_args in sections.items():
                self.display_section(title, cli_args)

    @staticmethod
    def add_args(cli_args, parser, tuning=False):
        """
        Add given arguments to parser.
        Args:
            cli_args: A dictionary of args and options.
            parser: argparse.ArgumentParser

        Returns:
            None.
        """
        for arg, options in cli_args.items():
            _help = options.get('help')
            _default = options.get('default')
            _type = options.get('type')
            _action = options.get('action')
            _required = options.get('required')
            _nargs = options.get('nargs')
            _hp_type = options.get('hp_type')
            if tuning:
                if _hp_type:
                    _nargs = '*'
            if not _action:
                parser.add_argument(
                    f'--{arg}',
                    help=_help,
                    default=_default,
                    type=_type,
                    required=_required,
                    nargs=_nargs,
                )
            else:
                parser.add_argument(
                    f'--{arg}', help=_help, default=_default, action=_action
                )

    def maybe_create_agent(self, argv):
        """
        Display help respective to parsed commands or set self.agent_id and self.command
        for further execution if enough arguments are given.
        Args:
            argv: Arguments passed through sys.argv or otherwise.

        Returns:
            None
        """
        to_display = {}
        total = len(argv)
        if total == 0:
            self.display_commands()
            return
        command = argv[0]
        to_display.update(non_agent_args)
        to_display.update(agent_args)
        assert command in xagents.commands, f'Invalid command `{command}`'
        to_display.update(xagents.commands[command][0])
        if total == 1:
            self.display_commands({command: to_display})
            return
        agent_id = argv[1]
        assert agent_id in xagents.agents, f'Invalid agent `{agent_id}`'
        to_display.update(xagents.agents[agent_id]['module'].cli_args)
        if total == 2:
            title = f'{command} {agent_id}'
            if (
                issubclass(xagents.agents[agent_id]['agent'], OffPolicy)
                or agent_id == 'acer'
            ):
                to_display.update(off_policy_args)
            self.display_commands({title: to_display})
            return
        self.command, self.agent_id = command, agent_id

    def parse_all_groups(self, argv, tuning):
        general_parser = argparse.ArgumentParser()
        agent_parser = argparse.ArgumentParser()
        command_parser = argparse.ArgumentParser()
        self.add_args(agent_args, agent_parser, tuning)
        self.add_args(
            xagents.agents[self.agent_id]['module'].cli_args, agent_parser, tuning
        )
        self.add_args(xagents.commands[self.command][0], command_parser, tuning)
        if (
            issubclass(xagents.agents[self.agent_id]['agent'], OffPolicy)
            or self.agent_id == 'acer'
        ):
            self.add_args(off_policy_args, general_parser, tuning)
        self.add_args(non_agent_args, general_parser, tuning)
        non_agent_known, extra1 = general_parser.parse_known_args(argv)
        agent_known, extra2 = agent_parser.parse_known_args(argv)
        command_known, extra3 = command_parser.parse_known_args(argv)
        unknown_flags = [
            unknown_flag
            for unknown_flag in set(extra1) & set(extra2) & set(extra3)
            if unknown_flag not in [self.command, self.agent_id]
            and '--' in unknown_flag
        ]
        if unknown_flags:
            warnings.warn(f'Got unknown flags {unknown_flags}')
        return non_agent_known, agent_known, command_known

    def parse_known_args(self, argv, tuning=False):
        """
        Parse general, agent and command specific args.
        Args:
            argv: Arguments passed through sys.argv or otherwise.

        Returns:
            agent kwargs, non-agent kwargs and command kwargs.
        """
        non_agent_known, agent_known, command_known = self.parse_all_groups(
            argv, tuning
        )
        if self.command == 'train':
            assert (
                command_known.target_reward or command_known.max_steps
            ), 'train requires --target-reward or --max-steps'
        return agent_known, non_agent_known, command_known

    def execute(self, argv):
        """
        Parse command line arguments, display help or execute command
        if enough arguments are given.
        Args:
            argv: Arguments passed through sys.argv or otherwise.

        Returns:
            None
        """
        self.maybe_create_agent(argv)
        if not self.agent_id:
            return
        if self.command == 'tune':
            arg_groups = self.parse_all_groups(argv, True)
            return
        agent_known, non_agent_known, command_known = self.parse_known_args(
            argv,
        )
        agent_known = vars(agent_known)
        envs = create_envs(
            non_agent_known.env,
            non_agent_known.n_envs,
            non_agent_known.preprocess,
            scale_frames=not non_agent_known.no_env_scale,
            max_frame=non_agent_known.max_frame,
        )
        agent_known['envs'] = envs
        optimizer_kwargs = {
            'learning_rate': non_agent_known.lr,
            'beta_1': non_agent_known.beta1,
            'beta_2': non_agent_known.beta2,
            'epsilon': non_agent_known.opt_epsilon,
        }
        models = create_models(
            agent_known,
            envs[0],
            self.agent_id,
            optimizer_kwargs=optimizer_kwargs,
            seed=agent_known['seed'],
        )
        agent_known.update(models)
        if (
            issubclass(xagents.agents[self.agent_id]['agent'], OffPolicy)
            or self.agent_id == 'acer'
        ):
            buffers = create_buffers(
                self.agent_id,
                non_agent_known.buffer_max_size,
                non_agent_known.buffer_batch_size,
                non_agent_known.n_envs,
                agent_known['gamma'],
                non_agent_known.buffer_n_steps,
                non_agent_known.buffer_initial_size,
            )
            agent_known['buffers'] = buffers
        self.agent = xagents.agents[self.agent_id]['agent'](**agent_known)
        if non_agent_known.weights:
            n_weights = len(non_agent_known.weights)
            n_models = len(self.agent.output_models)
            assert (
                n_weights == n_models
            ), f'Expected {n_models} weights to load, got {n_weights}'
            for weight, model in zip(non_agent_known.weights, self.agent.output_models):
                model.load_weights(weight).expect_partial()
        getattr(self.agent, xagents.commands[self.command][1])(**vars(command_known))


def execute(argv=None):
    """
    Parse and execute commands.
    Args:
        argv: List of arguments to be passed to Executor.execute()
            if not specified, defaults. to sys.argv[1:]

    Returns:
        None
    """
    argv = argv or sys.argv[1:]
    Executor().execute(argv)


if __name__ == '__main__':
    execute()
