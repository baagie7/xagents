import configparser
from collections import deque

import cv2
import gym
import numpy as np
from tensorflow.keras.initializers import Orthogonal
from tensorflow.keras.layers import Conv2D, Dense, Flatten, Input
from tensorflow.keras.models import Model


class AtariPreprocessor(gym.Wrapper):
    """
    gym wrapper for preprocessing atari frames.
    """

    def __init__(
        self,
        env,
        frame_skips=4,
        resize_shape=(84, 84),
        state_buffer_size=2,
        scale_frames=True,
    ):
        """
        Initialize preprocessing settings.
        Args:
            env: gym environment that returns states as atari frames.
            frame_skips: Number of frame skips to use per environment step.
            resize_shape: (m, n) output frame size.
            state_buffer_size: Buffer size which is used to hold frames during steps.
            scale_frames: If False, frames will not be scaled / normalized (divided by 255)
        """
        assert frame_skips > 1, 'frame_skips must be >= 1'
        super(AtariPreprocessor, self).__init__(env)
        self.skips = frame_skips
        self.frame_shape = resize_shape
        self.observation_space.shape = (*resize_shape, 1)
        self.observation_buffer = deque(maxlen=state_buffer_size)
        self.scale_frames = scale_frames

    def process_frame(self, frame):
        """
        Resize and convert atari frame to grayscale.
        Args:
            frame: Atari frame as numpy.ndarray

        Returns:
            Processed frame.
        """
        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        frame = cv2.resize(frame, self.frame_shape)
        if self.scale_frames:
            frame = frame / 255
        return np.expand_dims(frame, -1)

    def step(self, action):
        """
        Step respective to self.skips.
        Args:
            action: Action supported by self.env

        Returns:
            (state, reward, done, info)
        """
        total_reward = 0
        state, done, info = 3 * [None]
        max_frame = None
        for _ in range(self.skips):
            state, reward, done, info = self.env.step(action)
            self.observation_buffer.append(state)
            max_frame = np.max(np.stack(self.observation_buffer), axis=0)
            total_reward += reward
            if done:
                break
        return self.process_frame(max_frame), total_reward, done, info

    def reset(self, **kwargs):
        """
        Reset self.env
        Args:
            **kwargs: kwargs passed to self.env.reset()

        Returns:
            Processed atari frame.
        """
        self.observation_buffer.clear()
        observation = self.env.reset(**kwargs)
        self.observation_buffer.append(observation)
        return self.process_frame(observation)


def create_gym_env(env_name, n=1, preprocess=True, *args, **kwargs):
    """
    Create gym environment and initialize preprocessing settings.
    Args:
        env_name: Name of the environment to be passed to gym.make()
        n: Number of environments to create.
        preprocess: If True, AtariPreprocessor will be used.
        *args: args to be passed to AtariPreprocessor
        **kwargs: kwargs to be passed to AtariPreprocessor

    Returns:
        A list of gym environments.
    """
    envs = [gym.make(env_name) for _ in range(n)]
    if preprocess:
        envs = [AtariPreprocessor(env, *args, **kwargs) for env in envs]
    return envs


class ModelReader:
    """
    Model utility class to create basic keras models from configuration files.
    """

    def __init__(self, cfg_file, output_units, input_shape, optimizer=None, seed=None):
        """
        Initialize model parser.
        Args:
            cfg_file: Path to .cfg file having that will be created.
            output_units: A list of output units that must be of the
                same size as the number of dense layers in the configuration
                without specified units.
            input_shape: input shape passed to tf.keras.layers.Input()
            optimizer: tf.keras.optimizers.Optimizer with which the resulting
                model will be compiled.
            seed: Random seed used by layer initializers.
        """
        self.initializers = {'orthogonal': Orthogonal}
        with open(cfg_file) as cfg:
            self.parser = configparser.ConfigParser()
            self.parser.read_file(cfg)
        self.optimizer = optimizer
        self.output_units = output_units
        self.input_shape = input_shape
        self.seed = seed
        self.output_count = 0

    def get_initializer(self, section):
        """
        Get layer initializer if specified in the configuration.
        Args:
            section: str, representing section unique name.

        Returns:
            tf.keras.initializers.Initializer
        """
        initializer_name = self.parser[section].get('initializer')
        gain = self.parser[section].get('gain')
        initializer_kwargs = {'seed': self.seed}
        if gain:
            initializer_kwargs.update({'gain': float(gain)})
        initializer = self.initializers.get(initializer_name)
        if initializer:
            return initializer(**initializer_kwargs)

    def create_convolution(self, section):
        """
        Parse convolution layer parameters and create layer.
        Args:
            section: str, representing section unique name.

        Returns:
            tf.keras.layers.Conv2D
        """
        filters = int(self.parser[section]['filters'])
        kernel_size = int(self.parser[section]['size'])
        stride = int(self.parser[section]['stride'])
        activation = self.parser[section].get('activation')
        return Conv2D(
            filters,
            kernel_size,
            stride,
            activation=activation,
            kernel_initializer=self.get_initializer(section),
        )

    def create_dense(self, section):
        """
        Parse dense layer parameters and create layer.
        Args:
            section: str, representing section unique name.

        Returns:
            tf.keras.layers.Dense
        """
        units = self.parser[section].get('units')
        if not units:
            assert (
                len(self.output_units) > self.output_count
            ), 'Output units given are less than dense layers required'
            units = self.output_units[self.output_count]
            self.output_count += 1
        activation = self.parser[section].get('activation')
        return Dense(
            units, activation, kernel_initializer=self.get_initializer(section)
        )

    def build_model(self):
        """
        Parse all configuration sections, create respective layers, create and
        compile model.

        Returns:
            tf.keras.Model
        """
        outputs = []
        common_layer = None
        input_layer = current_layer = Input(self.input_shape)
        for section in self.parser.sections():
            if section.startswith('convolutional'):
                current_layer = self.create_convolution(section)(current_layer)
            if section.startswith('flatten'):
                current_layer = Flatten()(current_layer)
            if section.startswith('dense'):
                current_layer = self.create_dense(section)(
                    common_layer if common_layer is not None else current_layer
                )
            if self.parser[section].get('common'):
                common_layer = current_layer
            if self.parser[section].get('output'):
                outputs.append(current_layer)
        self.output_count = 0
        model = Model(input_layer, outputs)
        if self.optimizer:
            model.compile(self.optimizer)
        return model
