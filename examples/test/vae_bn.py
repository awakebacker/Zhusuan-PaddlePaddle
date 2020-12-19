

import paddle
import paddle.fluid as fluid
import os
import math
import gzip
import progressbar
import six
import numpy as np
from six.moves import urllib, range
from six.moves import cPickle as pickle
from PIL import Image
from matplotlib import pyplot as plt


device = paddle.set_device('gpu') # or 'gpu'
paddle.disable_static(device)

pbar = None
examples_dir = os.path.dirname(os.path.abspath(__file__))
data_dir = os.path.join(examples_dir, "data")

def show_progress(block_num, block_size, total_size):
    global pbar
    if pbar is None:
        if total_size > 0:
            prefixes = ('', 'Ki', 'Mi', 'Gi', 'Ti', 'Pi', 'Ei', 'Zi', 'Yi')
            power = min(int(math.log(total_size, 2) / 10), len(prefixes) - 1)
            scaled = float(total_size) / (2 ** (10 * power))
            total_size_str = '{:.1f} {}B'.format(scaled, prefixes[power])
            try:
                marker = '█'
            except UnicodeEncodeError:
                marker = '*'
            widgets = [
                progressbar.Percentage(),
                ' ', progressbar.DataSize(),
                ' / ', total_size_str,
                ' ', progressbar.Bar(marker=marker),
                ' ', progressbar.ETA(),
                ' ', progressbar.AdaptiveTransferSpeed(),
            ]
            pbar = progressbar.ProgressBar(widgets=widgets,
                                           max_value=total_size)
        else:
            widgets = [
                progressbar.DataSize(),
                ' ', progressbar.Bar(marker=progressbar.RotatingMarker()),
                ' ', progressbar.Timer(),
                ' ', progressbar.AdaptiveTransferSpeed(),
            ]
            pbar = progressbar.ProgressBar(widgets=widgets,
                                           max_value=progressbar.UnknownLength)

    downloaded = block_num * block_size
    if downloaded < total_size:
        pbar.update(downloaded)
    else:
        pbar.finish()
        pbar = None

def download_dataset(url, path):
    print('Downloading data from %s' % url)
    urllib.request.urlretrieve(url, path, show_progress)

def to_one_hot(x, depth):
    """
    Get one-hot representation of a 1-D numpy array of integers.

    :param x: 1-D Numpy array of type int.
    :param depth: A int.

    :return: 2-D Numpy array of type int.
    """
    ret = np.zeros((x.shape[0], depth))
    ret[np.arange(x.shape[0]), x] = 1
    return ret

def load_mnist_realval(path, one_hot=True, dequantify=False):
    """
    Loads the real valued MNIST dataset.

    :param path: Path to the dataset file.
    :param one_hot: Whether to use one-hot representation for the labels.
    :param dequantify:  Whether to add uniform noise to dequantify the data
        following (Uria, 2013).

    :return: The MNIST dataset.
    """
    if not os.path.isfile(path):
        data_dir = os.path.dirname(path)
        if not os.path.exists(os.path.dirname(path)):
            os.makedirs(data_dir)
        download_dataset('http://www.iro.umontreal.ca/~lisa/deep/data/mnist'
                         '/mnist.pkl.gz', path)

    f = gzip.open(path, 'rb')
    if six.PY2:
        train_set, valid_set, test_set = pickle.load(f)
    else:
        train_set, valid_set, test_set = pickle.load(f, encoding='latin1')
    f.close()
    x_train, t_train = train_set[0], train_set[1]
    x_valid, t_valid = valid_set[0], valid_set[1]
    x_test, t_test = test_set[0], test_set[1]
    if dequantify:
        x_train += np.random.uniform(0, 1. / 256,
                                     size=x_train.shape).astype('float32')
        x_valid += np.random.uniform(0, 1. / 256,
                                     size=x_valid.shape).astype('float32')
        x_test += np.random.uniform(0, 1. / 256,
                                    size=x_test.shape).astype('float32')
    n_y = t_train.max() + 1
    t_transform = (lambda x: to_one_hot(x, n_y)) if one_hot else (lambda x: x)
    return x_train, t_transform(t_train), x_valid, t_transform(t_valid), \
        x_test, t_transform(t_test)



# 模型参数设定
new_im = Image.new('L', (280, 280))
image_size = 28*28
h_dim = 512
z_dim = 20 #20
num_epochs = 500
batch_size = 512
learning_rate = 1e-2







class VAE(paddle.nn.Layer):
    def __init__(self):
        super(VAE, self).__init__()

        self.fc0 = paddle.nn.Linear(image_size, h_dim)
        # # input => h
        self.fc1 = paddle.nn.Linear(h_dim, z_dim)
        self.act1 = paddle.nn.ReLU()
        # # h => mu and variance
        self.fc2 = paddle.nn.Linear(z_dim, z_dim)
        self.act2 = paddle.nn.ReLU()
        self.fc3 = paddle.nn.Linear(z_dim, z_dim)
        # # sampled z => h
        self.fc4 = paddle.nn.Linear(z_dim, h_dim)
        # # h => image
        self.fc5 = paddle.nn.Linear(h_dim, image_size)
        self.sigmoid = paddle.nn.Sigmoid()

    def encode(self, x):
        h = self.act1(self.fc1(  self.fc0(x)  ))
        # mu, log_variance
        return self.fc2(h), self.fc3(h)

    def reparameterize(self, mu, log_var):
        #  根据每个样本计算出的均值和方差，针对高斯分布随机产生相应的Z向量
        std = paddle.exp(log_var * 0.5)
        eps = paddle.normal(shape=paddle.shape(std))
        return mu + eps * std

    def decode_logits(self, z):
        # 将z进行解码
        h = self.act2(self.fc4(z))
        return self.fc5(h)

    def decode(self, z):
        # sigmoid激活
        return self.sigmoid(self.decode_logits(z))

    def forward(self, inputs, training=None, mask=None):
        # encoder
        mu, log_var = self.encode(inputs)
        # sample
        z = self.reparameterize(mu, log_var)
        # decode
        x_reconstructed_logits = self.decode_logits(z)

        return x_reconstructed_logits, mu, log_var


def main():
    # 加载MINIST数据集
    data_path = os.path.join(data_dir, "mnist.pkl.gz")
    x_train, t_train, x_valid, t_valid, x_test, t_test = load_mnist_realval(data_path)

    model = VAE()
    clip = fluid.clip.GradientClipByNorm(clip_norm=1.0)
    optimizer = paddle.optimizer.Adam(learning_rate=learning_rate, parameters=model.parameters(), grad_clip = clip)

    # 数据预处理
    num_batches = x_train.shape[0] // batch_size

    for epoch in range(num_epochs):
        # 根据数据集训练VAE，更新参数
        for step in range(num_batches):
            x = paddle.to_tensor(x_train[step:step+batch_size])
            x = paddle.reshape(x,[-1, image_size])

            # VAE前向计算
            x_reconstruction_logits, mu, log_var = model.forward(x)
            # 损失函数：计算重构与输入之间的sigmoid交叉熵
            reconstruction_loss = fluid.layers.sigmoid_cross_entropy_with_logits(label=x, x=x_reconstruction_logits)
            reconstruction_loss = paddle.reduce_sum(input=reconstruction_loss) / batch_size
            # 计算两个高斯分布之间的散度KL 未知的为第一个高斯分布 已知N为(0,1)的分布为第二个
            kl_div = - 0.5 * paddle.reduce_sum(1. + log_var - paddle.square(mu) - paddle.exp(log_var), dim=-1)
            kl_div = paddle.reduce_mean(kl_div)
            # 损失=重构误差+分布误差
            loss = paddle.reduce_mean(reconstruction_loss) + kl_div
            loss.backward()
            optimizer.step()
            optimizer.clear_grad()
            if (step + 1) % 50 == 0 or (step+1) == batch_size:
                print("Epoch[{}/{}], Step [{}/{}], Loss: {:.4f}, Reconst Loss: {:.4f}, KL Div: {:.4f}"
                      .format(epoch + 1, num_epochs, step + 1, num_batches, float(loss.numpy()),
                              float(reconstruction_loss.numpy()), float(kl_div.numpy())))

        # 计算当前参数组成的VAE下的z
        z = paddle.normal(shape=(batch_size, z_dim))
        # 将z用sigmoid激活函数使输出在固定区间
        out = model.decode(z)
        out = paddle.reshape(out, [-1, 28, 28]).numpy() * 255
        out = out.astype(np.uint8)

        index = 0
        for i in range(0, 280, 28):
            for j in range(0, 280, 28):
                im = out[index]
                im = Image.fromarray(im, mode='L')
                new_im.paste(im, (i, j))
                index += 1
        if epoch%10 == 0 or epoch==num_epochs-1:
            new_im.save('result/vae_sampled_epoch_%d.png' % (epoch + 1))
        # plt.imshow(np.asarray(new_im))
        # plt.show()

        out_logits, _, _ = model.forward(x[:batch_size // 2])
        out = fluid.layers.sigmoid(out_logits)  # out is just the logits, use sigmoid
        out = paddle.reshape(out, [-1, 28, 28]).numpy() * 255
        x = paddle.reshape(x[:batch_size // 2], [-1, 28, 28]).numpy()
        x_concat = np.concatenate([x, out], axis=0) * 255.
        x_concat = x_concat.astype(np.uint8)

        index = 0
        for i in range(0, 280, 28):
            for j in range(0, 280, 28):
                im = x_concat[index]
                im = Image.fromarray(im, mode='L')
                new_im.paste(im, (i, j))
                index += 1

        if epoch%10 == 0 or epoch==num_epochs-1:
            new_im.save('result/vae_reconstructed_epoch_%d.png' % (epoch + 1))
        # plt.imshow(np.asarray(new_im))
        # plt.show()
        print('New images saved !')




if __name__ == '__main__':
    main()