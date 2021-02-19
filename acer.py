import numpy as np
import tensorflow as tf

from a2c import A2C
from utils import ReplayBuffer


class ACER(A2C):
    def __init__(
        self,
        envs,
        model,
        n_steps=20,
        buffer_max_size=10000,
        replay_ratio=4,
        epsilon=1e-6,
        delta=1,
        *args,
        **kwargs,
    ):
        super(ACER, self).__init__(envs, model, n_steps=n_steps, *args, **kwargs)
        self.buffers = [
            ReplayBuffer(buffer_max_size, batch_size=self.n_envs * self.n_steps)
            for _ in range(self.n_envs)
        ]
        self.replay_ratio = replay_ratio
        self.epsilon = epsilon
        self.delta = delta

    def np_train_step(self):
        (
            states,
            rewards,
            actions,
            values,
            dones,
            log_probs,
            entropies,
            actor_features,
        ) = [np.asarray(item, np.float32) for item in self.get_batch()]
        return [
            a.swapaxes(0, 1).reshape(a.shape[0] * a.shape[1], *a.shape[2:])
            for a in [
                states,
                rewards,
                actions,
                values,
                dones,
                log_probs,
                entropies,
                actor_features,
            ]
        ]

    # @tf.function
    def train_step(self):
        batch = (
            states,
            rewards,
            actions,
            values,
            dones,
            log_probs,
            entropies,
            actor_features,
        ) = tf.numpy_function(self.np_train_step, [], [tf.float32 for _ in range(8)])
        pass


if __name__ == '__main__':
    # A: actions, R: rewards, D: dones, MU: actor_features, LR: learning_rate

    from tensorflow.keras.optimizers import Adam
    from tensorflow_addons.optimizers import MovingAverage

    from models import CNNA2C
    from utils import create_gym_env

    envi = create_gym_env('PongNoFrameskip-v4', 2)
    m = CNNA2C(
        envi[0].observation_space.shape,
        envi[0].action_space.n,
        actor_activation='softmax',
    )
    o = MovingAverage(Adam(7e-4))
    agn = ACER(envi, m, optimizer=o)
    agn.fit(19)
