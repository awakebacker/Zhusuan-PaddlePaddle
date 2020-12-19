import numpy as np
import paddle
import paddle.fluid as fluid

from .base import Distribution

__all__ = [
    'FoldNormal'
]

class FoldNormal(Distribution):
    def __init__(self,
                 dtype='float32',
                 param_dtype='float32',
                 is_continues=True,
                 is_reparameterized=True,
                 group_ndims=0,
                 **kwargs):
        super(FoldNormal, self).__init__(dtype,
                             param_dtype,
                             is_continues,
                             is_reparameterized,
                             group_ndims=group_ndims,
                             **kwargs)
        try:
            self._std = kwargs['std']
            self._logstd = paddle.log(self._std)
        except:
            self._logstd = kwargs['logstd']
            self._std = paddle.exp(self._logstd)

        self._mean = kwargs['mean']

    @property
    def mean(self):
        """The mean of the Normal distribution."""
        return self._mean

    @property
    def logstd(self):
        """The log standard deviation of the Normal distribution."""
        try:
            return self._logstd
        except:
            self._logstd = paddle.log(self._std)
            return self._logstd

    @property
    def std(self):
        """The standard deviation of the Normal distribution."""
        return self._std

    def _sample(self, n_samples=1, **kwargs):
        # if n_samples > 1:
        _shape = fluid.layers.shape(self._mean)
        _shape = fluid.layers.concat([paddle.to_tensor([n_samples], dtype="int32"), _shape])
        _len = len(self._mean.shape)

        if n_samples > 1:
            _std = paddle.tile(self._std, repeat_times=[n_samples, *_len*[1]])
            _mean = paddle.tile(self._mean, repeat_times=[n_samples, *_len*[1]])
        else:
            _shape = fluid.layers.shape(self._mean)
            _std = self._std + 0.
            _mean = self._mean + 0.

        if not self.is_reparameterized:
            _mean.stop_gradient = True
            _std.stop_gradient = True

        sample_ = paddle.randn(name='sample', shape=_shape, dtype=self.dtype) * _std + _mean
        sample_ = paddle.cast( sample_, dtype=_mean.dtype)
        sample_.stop_gradient = False
        self.sample_cache = sample_
        if n_samples > 1:
            assert(sample_.shape[0] == n_samples)

        return sample_

    def _log_prob(self, sample=None):
        if sample is None:
            sample = self.sample_cache

        if len(sample.shape) > len(self._mean.shape):
            n_samples = sample.shape[0]
            _len = len(self._std.shape)
            _std = paddle.tile(self._std, repeat_times=[n_samples, *_len*[1]])
            _mean = paddle.tile(self._mean, repeat_times=[n_samples, *_len*[1]])
        else:
            _std = self._std
            _mean = self._mean

        if not self.is_reparameterized:
            _mean.stop_gradient = True
            _std.stop_gradient = True

        ## Log Prob
        sample = paddle.cast(sample, dtype=self.dtype)
        logstd = paddle.log(_std)
        c = -0.5 * (np.log(2.0) + np.log(np.pi))
        # c = -0.5 * np.log(2 * np.pi)
        precision = paddle.exp(-2.0 * logstd)
        mask = paddle.log(paddle.cast(sample >= 0., dtype=self.dtype))
        log_prob = (c - (logstd + 0.5 * precision * paddle.square(sample - _mean)) +
                fluid.layers.softplus(-2.0 * _mean * sample * precision)) + mask

        # log_prob = fluid.layers.reduce_sum(log_prob_sample, dim=-1)
        log_prob.stop_gradient = False
        return log_prob

