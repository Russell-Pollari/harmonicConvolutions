"""
Harmonic Network Definitions

This file contains the definition of our neural network models. This
should be used an example of how to create a harmonic network using our 
helper functions in tensorflow.

"""
import tensorflow as tf

import harmonic_network_lite as hn_lite

from harmonic_network_helpers import *

def deep_mnist(opt, x, train_phase, device='/cpu:0'):
	"""High frequency convolutions are unstable, so get rid of them"""
	# Max order
	mo = 1
	# Number of Filters
	nf = opt['n_filters']
	nf2 = int(nf*opt['filter_gain'])
	nf3 = int(nf*(opt['filter_gain']**2.))
	bs = opt['batch_size']
	fs = opt['filter_size']
	nch = opt['n_channels']
	ncl = opt['n_classes']
	d = device
	sm = opt['std_mult']

	# Create bias for final layer
	with tf.device(device):
		bias = tf.get_variable('b7', shape=[opt['n_classes']],
							   initializer=tf.constant_initializer(1e-2))
		x = tf.reshape(x, shape=[bs,opt['dim'],opt['dim'],1,1,nch])
	
	# Convolutional Layers with pooling
	with tf.name_scope('block1') as scope:
		cv1 = hn_lite.conv2d(x, nf, fs, max_order=mo, padding='SAME', name='1', device=d)
		cv1 = hn_lite.nonlinearity(cv1, tf.nn.relu, name='1', device=d)
		
		cv2 = hn_lite.conv2d(cv1, nf, fs, max_order=mo, padding='SAME', name='2', device=d)
		cv2 = hn_lite.batch_norm(cv2, train_phase, name='bn1', device=d)

	with tf.name_scope('block2') as scope:
		cv2 = hn_lite.mean_pool(cv2, ksize=(1,2,2,1), strides=(1,2,2,1))
		cv3 = hn_lite.conv2d(cv2, nf2, fs, max_order=mo, padding='SAME', name='3', device=d)
		cv3 = hn_lite.nonlinearity(cv3, tf.nn.relu, name='3', device=d)

		cv4 = hn_lite.conv2d(cv3, nf2, fs, max_order=mo, padding='SAME', name='4', device=d)
		cv4 = hn_lite.batch_norm(cv4, train_phase, name='bn2', device=d)

	with tf.name_scope('block3') as scope:
		cv4 = hn_lite.mean_pool(cv4, ksize=(1,2,2,1), strides=(1,2,2,1))
		cv5 = hn_lite.conv2d(cv4, nf3, fs, max_order=mo, padding='SAME', name='5', device=d)
		cv5 = hn_lite.nonlinearity(cv5, tf.nn.relu, name='5', device=d)

		cv6 = hn_lite.conv2d(cv5, nf3, fs, max_order=mo, padding='SAME', name='6', device=d)
		cv6 = hn_lite.batch_norm(cv6, train_phase, name='bn3', device=d)

	# Final Layer
	with tf.name_scope('block4') as scope:
		cv7 = hn_lite.conv2d(cv6, ncl, fs, max_order=mo, padding='SAME', phase=False,
					 name='7', device=d)
		real = hn_lite.sum_magnitudes(cv7)
		cv7 = tf.reduce_mean(real, reduction_indices=[1,2,3,4])
		return tf.nn.bias_add(cv7, bias)


def Zresidual_block(x, n_channels, ksize, depth, is_training, fnc=tf.nn.relu,
						 max_order=1, phase=True, name='res', device='/cpu:0'):
	"""Harmonic version of a residual block
	
	x: input tf tensor, shape [batchsize,height,width,channels,complex,order],
	e.g. a real input tensor of rotation order 0 could have shape
	[16,32,32,3,1,1], or a complex input tensor of rotation orders 0,1,2, could
	have shape [32,121,121,32,2,3]
	n_channels: number of output channels (int)
	ksize: size of square filter (int)
	depth: number of convolutions per block
	is_training: tf bool indicating training status
	fnc: nonlinearity applied to magnitudes (default tf.nn.relu)
	max_order: maximum rotation order e.g. max_order=2 uses 0,1,2 (default 1)
	phase: use a per-channel phase offset (default True)
	name: (default 'res')
	device: (default '/cpu:0')
	"""
	from harmonic_network_ops import Zbn
	
	with tf.name_scope(name) as scope:
		y = x
		for i in xrange(depth):
			ysh = y.get_shape().as_list()
			W = get_weights([ksize,ksize,ysh[3],n_channels], std_mult=1.,
				name=name+'W_c'+str(i), device=device)
			y = tf.nn.conv2d(y, W, (1,1,1,1), 'SAME', name=name+'_c'+str(i))
			y = Zbn(y, is_training, decay=0.99, name=name+'_nl'+str(i),
					 device=device)
			if i != (depth-1):
				y = tf.nn.relu(y)
		xsh = x.get_shape().as_list()
		x = tf.pad(x, [[0,0],[0,0],[0,0],[0,ysh[3]-xsh[3]]])
		return y + x


def wide_resnet(opt, x, train_phase, device='/cpu:0'):
	"""High frequency convolutions are unstable, so get rid of them"""
	# Abbreviations
	nf = opt['n_filters']
	fg = opt['filter_gain']
	bs = opt['batch_size']
	fs = opt['filter_size']
	N = opt['block_multiplicity']
	d = device
	
	with tf.device(device):
		initializer = tf.contrib.layers.variance_scaling_initializer()
		Win = get_weights([fs,fs,3,nf], std_mult=1., name='Win', device=device)
		Wgap = tf.get_variable('Wfc', shape=[fg*fg*nf,opt['n_classes']],
									  initializer=initializer)
		bgap = tf.get_variable('bfc', shape=[opt['n_classes']],
									  initializer=tf.constant_initializer(1e-2))

		x = tf.reshape(x, shape=[bs,opt['dim'],opt['dim'],opt['n_channels']])
	
	# Convolutional Layers
	with tf.device(d):
		res1 = tf.nn.conv2d(x, Win, (1,1,1,1), 'SAME', name='Win_conv')
	for i in xrange(N):
		name = 'r1_'+str(i)
		res1 = Zresidual_block(res1, nf, fs, 2, train_phase, name=name, device=d)
	res2 =tf.nn.max_pool(res1, (1,2,2,1), (1,2,2,1), 'VALID', name='mp1')
	
	for i in xrange(N):
		name = 'r2_'+str(i)
		res2 = Zresidual_block(res2, fg*nf, fs, 2, train_phase, name=name, device=d)
	res3 =tf.nn.max_pool(res2, (1,2,2,1), (1,2,2,1), 'VALID', name='mp2')
	
	for i in xrange(N):
		name = 'r3_'+str(i)
		res3 = Zresidual_block(res3, fg*fg*nf, fs, 2, train_phase, name=name, device=d)
	res4 =tf.nn.max_pool(res3, (1,2,2,1), (1,2,2,1), 'VALID', name='mp3')

	with tf.name_scope('gap') as scope:
		gap = tf.reduce_mean(res4, reduction_indices=[1,2])
		return tf.nn.bias_add(tf.matmul(gap, Wgap), bgap)


def h_VGG(opt, x, train_phase, device='/cpu:0'):
	"""High frequency convolutions are unstable, so get rid of them"""
	# Abbreviations
	nf = opt['n_filters']
	fg = opt['filter_gain']
	bs = opt['batch_size']
	fs = opt['filter_size']
	sm = opt['std_mult']
	mo = opt['max_order']
	nr = opt['n_rings']
	d = device
	tp = train_phase
	
	nf1 = nf
	nf2 = nf*fg
	nf3 = nf*(fg**2)
	nf4 = nf*(fg**3)
	nf5 = nf*(fg**3)
	
	with tf.device(device):
		initializer = tf.contrib.layers.variance_scaling_initializer()
		Wg = tf.get_variable('Wg', shape=[nf5*(mo+1),opt['n_classes']], initializer=initializer)
		bg = tf.get_variable('bg', shape=[opt['n_classes']], initializer=tf.constant_initializer(1e-2))

		x = tf.reshape(x, shape=[bs,opt['dim'],opt['dim'],1,1,opt['n_channels']])
	
	activations = []
	
	# Block 1
	res1_1 = hn_lite.conv2d(x, nf1, fs, max_order=mo, n_rings=nr, padding='SAME', name='1_1', device=d)
	res1_1 = hn_lite.batch_norm(res1_1, tp, tf.nn.relu, name='n1_1', device=d)
	res1_2 = hn_lite.conv2d(res1_1, nf1, fs, max_order=mo, n_rings=nr, padding='SAME', name='1_2', device=d)
	res1_2 = hn_lite.batch_norm(res1_2, tp, fnc=tf.nn.relu, name='n1_2', device=d)
	res1_mp = hn_lite.mean_pool(res1_2, ksize=(1,2,2,1), strides=(1,2,2,1), name='1_mp')
	
	# Block 2
	res2_1 = hn_lite.conv2d(res1_mp, nf2, fs, max_order=mo, n_rings=nr, padding='SAME', name='2_1', device=d)
	res2_1 = hn_lite.batch_norm(res2_1, tp, tf.nn.relu, name='n2_1', device=d)
	res2_2 = hn_lite.conv2d(res2_1, nf2, fs, max_order=mo, n_rings=nr, padding='SAME', name='2_2', device=d)
	res2_2 = hn_lite.batch_norm(res2_2, tp, tf.nn.relu, name='n2_2', device=d)
	res2_mp = hn_lite.mean_pool(res2_2, ksize=(1,2,2,1), strides=(1,2,2,1), name='2_mp')
	
	# Block 3
	res3_1 = hn_lite.conv2d(res2_mp, nf3, fs, max_order=mo, n_rings=nr, padding='SAME', name='3_1', device=d)
	res3_1 = hn_lite.batch_norm(res3_1, tp, tf.nn.relu, name='n3_1', device=d)
	res3_2 = hn_lite.conv2d(res3_1, nf3, fs, max_order=mo, n_rings=nr, padding='SAME', name='3_2', device=d)
	res3_2 = hn_lite.batch_norm(res3_2, tp, tf.nn.relu, name='n3_2', device=d)
	res3_3 = hn_lite.conv2d(res3_2, nf3, fs, max_order=mo, n_rings=nr, padding='SAME', name='3_3', device=d)
	res3_3 = hn_lite.batch_norm(res3_3, tp, tf.nn.relu, name='n3_3', device=d)
	#res3_mp = hn_lite.mean_pool(res3_3, ksize=(1,2,2,1), strides=(1,2,2,1), name='3_mp')
	
	# Block 4
	res4_1 = hn_lite.conv2d(res3_3, nf4, fs, max_order=mo, n_rings=nr, padding='SAME', name='4_1', device=d)
	res4_1 = hn_lite.batch_norm(res4_1, tp, tf.nn.relu, name='n4_1', device=d)
	res4_2 = hn_lite.conv2d(res4_1, nf4, fs, max_order=mo, n_rings=nr, padding='SAME', name='4_2', device=d)
	res4_2 = hn_lite.batch_norm(res4_2, tp, tf.nn.relu, name='n4_2', device=d)
	res4_3 = hn_lite.conv2d(res4_2, nf4, fs, max_order=mo, n_rings=nr, padding='SAME', name='4_3', device=d)
	res4_3 = hn_lite.batch_norm(res4_3, tp, tf.nn.relu, name='n4_3', device=d)
	#res4_mp = hn_lite.mean_pool(res4_3, ksize=(1,2,2,1), strides=(1,2,2,1), name='4_mp')
	
	# Block 5
	res5_1 = hn_lite.conv2d(res4_3, nf5, fs, max_order=mo, n_rings=nr, padding='SAME', name='5_1', device=d)
	res5_1 = hn_lite.batch_norm(res5_1, tp, tf.nn.relu, name='n5_1', device=d)
	res5_2 = hn_lite.conv2d(res5_1, nf5, fs, max_order=mo, n_rings=nr, padding='SAME', name='5_2', device=d)
	res5_2 = hn_lite.batch_norm(res5_2, tp, tf.nn.relu, name='n5_2', device=d)
	res5_3 = hn_lite.conv2d(res5_2, nf5, fs, max_order=mo, n_rings=nr, padding='SAME', name='5_3', device=d)
	res5_3 = hn_lite.batch_norm(res5_3, tp, tf.nn.relu, name='n5_3', device=d)
	#res5_mp = hn_lite.mean_pool(res5_3, ksize=(1,2,2,1), strides=(1,2,2,1), name='5_mp')
	

	with tf.name_scope('gap') as scope:
		mags = hn_lite.stack_magnitudes(res5_3, keep_dims=False)
		gap = tf.reduce_mean(mags, reduction_indices=[1,2])
		gapsh = gap.get_shape().as_list()
		gap = tf.reshape(gap, tf.pack([gapsh[0],-1]))
		
		return tf.nn.bias_add(tf.matmul(gap, Wg), bg)


def h_block(opt, x, n_channels, n_layers, is_training, fnc=tf.nn.relu,
				name='name', mean_pool=True, device='/cpu:0'):
	"""A single block of h-convolutions"""
	fs = opt['filter_size']
	mo = opt['max_order']
	nr = opt['n_rings']
	d = device
	for i in xrange(n_layers):
		x = hn_lite.conv2d(x, n_channels, fs, max_order=mo, n_rings=nr,
								 padding='SAME', name='hc'+name+'_'+str(i), device=d)
		x = hn_lite.batch_norm(x, is_training, tf.nn.relu,
									  name='hbn'+name+'_'+str(i), device=d)
	if mean_pool:
		x = hn_lite.mean_pool(x, ksize=(1,2,2,1), strides=(1,2,2,1),
									 name='mp_'+name)
	return x


def Z_block(opt, x, n_channels, n_layers, is_training, fnc, name='name',
				device='/cpu:0'):
	"""A single block of h-convolutions"""
	fs = opt['filter_size']
	mo = opt['max_order']
	nr = opt['n_rings']
	d = device
	for i in xrange(n_layers):
		x = hn_lite.Z_conv(x, n_channels, fs, max_order=mo, n_rings=nr,
								 padding='SAME', name='Zc'+name+'_'+str(i), device=d)
		x = hn_lite.Z_batch_norm(x, is_training, fnc, name='Zbn'+name+'_'+str(i),
										 device=d)
	return x


def mixed_VGG(opt, x, train_phase, device='/cpu:0'):
	"""H-Net layers followed by regular convolutions"""
	# Defines
	nf = opt['n_filters']
	fg = opt['filter_gain']
	bs = opt['batch_size']
	fs = opt['filter_size']
	sm = opt['std_mult']
	mo = opt['max_order']
	nr = opt['n_rings']
	d = device
	tp = train_phase
	
	assert opt['block_multiplicity'] <= 5
	
	nf1 = nf
	nf2 = nf*fg
	nf3 = nf*(fg**2)
	nf4 = nf*(fg**3)
	nf5 = nf*(fg**3)
	
	# Variables for the dense layer at the end
	with tf.device(device):
		initializer = tf.contrib.layers.variance_scaling_initializer()
		Wg = tf.get_variable('Wg', shape=[nf5,opt['n_classes']],
									initializer=initializer)
		bg = tf.get_variable('bg', shape=[opt['n_classes']],
									initializer=tf.constant_initializer(1e-2))
		
		# Reshape for H-Net input
		x = tf.reshape(x, shape=[bs,opt['dim'],opt['dim'],1,1,opt['n_channels']])
	
	# H-Net Blocks
	mp = True
	for i in xrange(5):
		# Choose whether to mean-pool
		if i >= 2:
			mp = False
		# Num channels
		nc = nf*(fg**i)
		# Reshape from h-form to Z-form
		if i == opt['block_multiplicity']:
			x = hn_lite.stack_magnitudes(x, keep_dims=False)
			xsh = x.get_shape().as_list()
			x = tf.reshape(x, tf.pack([xsh[0],xsh[1],xsh[2],-1]))
		# Apply an h/Z=block
		if i < opt['block_multiplicity']:
			x = h_block(opt, x, nc, 2, tp, tf.nn.relu, mean_pool=mp, name=str(i))
		else:
			x = Z_block(opt, x, nc, 2, tp, tf.nn.relu, max_pool=mp, name=str(i))
	
	# If the network end in h_convs reshape
	if opt['block_multiplicity'] == 5:
			x = hn_lite.stack_magnitudes(x, keep_dims=False)
			x = tf.reduce_mean(x, reduction_indices=[1,2])
			xsh = x.get_shape().as_list()
			x = tf.reshape(x, tf.pack([xsh[0],-1]))
			
	# Dense layers at end of network
	with tf.name_scope('gap') as scope:
		gap = tf.nn.relu(tf.reduce_mean(x, reduction_indices=[1,2]))
		return tf.nn.bias_add(tf.matmul(gap, Wg), bg)


def mixed_VGG_(opt, x, train_phase, device='/cpu:0'):
	"""H-Net layers followed by regular convolutions"""
	# Abbreviations
	nf = opt['n_filters']
	fg = opt['filter_gain']
	bs = opt['batch_size']
	fs = opt['filter_size']
	sm = opt['std_mult']
	mo = opt['max_order']
	nr = opt['n_rings']
	d = device
	tp = train_phase
	
	nf1 = nf
	nf2 = nf*fg
	nf3 = nf*(fg**2)
	nf4 = nf*(fg**3)
	nf5 = nf*(fg**3)
	
	with tf.device(device):
		initializer = tf.contrib.layers.variance_scaling_initializer()
		Wg = tf.get_variable('Wg', shape=[nf5,opt['n_classes']], initializer=initializer)
		bg = tf.get_variable('bg', shape=[opt['n_classes']], initializer=tf.constant_initializer(1e-2))

		x = tf.reshape(x, shape=[bs,opt['dim'],opt['dim'],1,1,opt['n_channels']])
	
	activations = []
	
	# Block 1
	res1_1 = hn_lite.conv2d(x, nf1, fs, max_order=mo, n_rings=nr, padding='SAME', name='1_1', device=d)
	res1_1 = hn_lite.batch_norm(res1_1, tp, tf.nn.relu, name='n1_1', device=d)
	res1_2 = hn_lite.conv2d(res1_1, nf1, fs, max_order=mo, n_rings=nr, padding='SAME', name='1_2', device=d)
	res1_2 = hn_lite.batch_norm(res1_2, tp, fnc=tf.nn.relu, name='n1_2', device=d)
	res1_mp = hn_lite.mean_pool(res1_2, ksize=(1,2,2,1), strides=(1,2,2,1), name='1_mp')
	res1_mag = hn_lite.stack_magnitudes(res1_mp, keep_dims=False)
	rsh = res1_mag.get_shape().as_list()
	res1_mag = tf.reshape(res1_mag, tf.pack([rsh[0],rsh[1],rsh[2],-1]))
	
	# Block 2
	res2_1 = hn_lite.Z_conv(res1_mag, nf2, fs, padding='SAME', name='2_1', device=d)
	res2_1 = hn_lite.Z_batch_norm(res2_1, tp, name='n2_1', device=d)
	res2_2 = hn_lite.Z_conv(tf.nn.relu(res2_1), nf2, fs, padding='SAME', name='2_2', device=d)
	res2_2 = hn_lite.Z_batch_norm(res2_2, tp, name='n2_2', device=d)
	res2_mp = tf.nn.max_pool(res2_2, ksize=(1,2,2,1), strides=(1,2,2,1), padding='VALID', name='2_mp')
	
	# Block 3
	res3_1 = hn_lite.Z_conv(tf.nn.relu(res2_mp), nf3, fs, padding='SAME', name='3_1',)
	res3_1 = hn_lite.Z_batch_norm(res3_1, tp, name='n3_1', device=d)
	res3_2 = hn_lite.Z_conv(tf.nn.relu(res3_1), nf3, fs, padding='SAME', name='3_2', device=d)
	res3_2 = hn_lite.Z_batch_norm(res3_2, tp, name='n3_2', device=d)
	res3_3 = hn_lite.Z_conv(tf.nn.relu(res3_2), nf3, fs, padding='SAME', name='3_3', device=d)
	res3_3 = hn_lite.Z_batch_norm(res3_3, tp, name='n3_3', device=d)
	
	# Block 4
	res4_1 = hn_lite.Z_conv(tf.nn.relu(res3_3), nf4, fs, padding='SAME', name='4_1', device=d)
	res4_1 = hn_lite.Z_batch_norm(res4_1, tp, name='n4_1', device=d)
	res4_2 = hn_lite.Z_conv(tf.nn.relu(res4_1), nf4, fs, padding='SAME', name='4_2', device=d)
	res4_2 = hn_lite.Z_batch_norm(res4_2, tp, name='n4_2', device=d)
	res4_3 = hn_lite.Z_conv(tf.nn.relu(res4_2), nf4, fs, padding='SAME', name='4_3', device=d)
	res4_3 = hn_lite.Z_batch_norm(res4_3, tp, name='n4_3', device=d)
	
	# Block 5
	res5_1 = hn_lite.Z_conv(tf.nn.relu(res4_3), nf5, fs, padding='SAME', name='5_1', device=d)
	res5_1 = hn_lite.Z_batch_norm(res5_1, tp, name='n5_1', device=d)
	res5_2 = hn_lite.Z_conv(tf.nn.relu(res5_1), nf5, fs, padding='SAME', name='5_2', device=d)
	res5_2 = hn_lite.Z_batch_norm(res5_2, tp, name='n5_2', device=d)
	res5_3 = hn_lite.Z_conv(tf.nn.relu(res5_2), nf5, fs, padding='SAME', name='5_3', device=d)
	res5_3 = hn_lite.Z_batch_norm(res5_3, tp, name='n5_3', device=d)
	

	with tf.name_scope('gap') as scope:
		gap = tf.nn.relu(tf.reduce_mean(res5_3, reduction_indices=[1,2]))
		return tf.nn.bias_add(tf.matmul(gap, Wg), bg)


def Z_VGG(opt, x, train_phase, device='/cpu:0'):
	"""High frequency convolutions are unstable, so get rid of them"""
	# Abbreviations
	nf = opt['n_filters']
	fg = opt['filter_gain']
	bs = opt['batch_size']
	fs = opt['filter_size']
	sm = opt['std_mult']
	mo = opt['max_order']
	nr = opt['n_rings']
	d = device
	tp = train_phase
	
	nf1 = nf
	nf2 = nf*fg
	nf3 = nf*(fg**2)
	nf4 = nf*(fg**3)
	nf5 = nf*(fg**3)
	
	with tf.device(device):
		initializer = tf.contrib.layers.variance_scaling_initializer()
		W = tf.get_variable('W', shape=[nf5,opt['n_classes']], initializer=initializer)
		b = tf.get_variable('b', shape=[opt['n_classes']], initializer=tf.constant_initializer(1e-2))

		x = tf.reshape(x, shape=[bs,opt['dim'],opt['dim'],opt['n_channels']])
	
	activations = []
	
	# Block 1
	res1_1 = hn_lite.Z_conv(x, nf1, fs, padding='SAME', name='1_1', device=d)
	res1_1 = hn_lite.Z_batch_norm(res1_1, tp, name='n1_1', device=d)
	res1_2 = hn_lite.Z_conv(tf.nn.relu(res1_1), nf1, fs, padding='SAME', name='1_2', device=d)
	res1_2 = hn_lite.Z_batch_norm(res1_2, tp, name='n1_2', device=d)
	res1_mp = tf.nn.max_pool(res1_2, ksize=(1,2,2,1), strides=(1,2,2,1), padding='VALID', name='1_mp')
	
	# Block 2
	res2_1 = hn_lite.Z_conv(res1_mp, nf2, fs, padding='SAME', name='2_1', device=d)
	res2_1 = hn_lite.Z_batch_norm(res2_1, tp, name='n2_1', device=d)
	res2_2 = hn_lite.Z_conv(tf.nn.relu(res2_1), nf2, fs, padding='SAME', name='2_2', device=d)
	res2_2 = hn_lite.Z_batch_norm(res2_2, tp, name='n2_2', device=d)
	res2_mp = tf.nn.max_pool(res2_2, ksize=(1,2,2,1), strides=(1,2,2,1), padding='VALID', name='2_mp')
	
	# Block 3
	res3_1 = hn_lite.Z_conv(tf.nn.relu(res2_mp), nf3, fs, padding='SAME', name='3_1',)
	res3_1 = hn_lite.Z_batch_norm(res3_1, tp, name='n3_1', device=d)
	res3_2 = hn_lite.Z_conv(tf.nn.relu(res3_1), nf3, fs, padding='SAME', name='3_2', device=d)
	res3_2 = hn_lite.Z_batch_norm(res3_2, tp, name='n3_2', device=d)
	res3_3 = hn_lite.Z_conv(tf.nn.relu(res3_2), nf3, fs, padding='SAME', name='3_3', device=d)
	res3_3 = hn_lite.Z_batch_norm(res3_3, tp, name='n3_3', device=d)
	
	# Block 4
	res4_1 = hn_lite.Z_conv(tf.nn.relu(res3_3), nf4, fs, padding='SAME', name='4_1', device=d)
	res4_1 = hn_lite.Z_batch_norm(res4_1, tp, name='n4_1', device=d)
	res4_2 = hn_lite.Z_conv(tf.nn.relu(res4_1), nf4, fs, padding='SAME', name='4_2', device=d)
	res4_2 = hn_lite.Z_batch_norm(res4_2, tp, name='n4_2', device=d)
	res4_3 = hn_lite.Z_conv(tf.nn.relu(res4_2), nf4, fs, padding='SAME', name='4_3', device=d)
	res4_3 = hn_lite.Z_batch_norm(res4_3, tp, name='n4_3', device=d)
	
	# Block 5
	res5_1 = hn_lite.Z_conv(tf.nn.relu(res4_3), nf5, fs, padding='SAME', name='5_1', device=d)
	res5_1 = hn_lite.Z_batch_norm(res5_1, tp, name='n5_1', device=d)
	res5_2 = hn_lite.Z_conv(tf.nn.relu(res5_1), nf5, fs, padding='SAME', name='5_2', device=d)
	res5_2 = hn_lite.Z_batch_norm(res5_2, tp, name='n5_2', device=d)
	res5_3 = hn_lite.Z_conv(tf.nn.relu(res5_2), nf5, fs, padding='SAME', name='5_3', device=d)
	res5_3 = hn_lite.Z_batch_norm(res5_3, tp, name='n5_3', device=d)
	

	with tf.name_scope('gap') as scope:
		gap = tf.nn.relu(tf.reduce_mean(res5_3, reduction_indices=[1,2]))
		return tf.nn.bias_add(tf.matmul(gap, W), b)


def h_resnet(opt, x, train_phase, device='/cpu:0'):
	"""High frequency convolutions are unstable, so get rid of them"""
	# Abbreviations
	nf = opt['n_filters']
	fg = opt['filter_gain']
	bs = opt['batch_size']
	fs = opt['filter_size']
	N = opt['block_multiplicity']
	sm = opt['std_mult']
	mo = opt['max_order']
	
	nf1 = nf
	nf2 = nf*fg
	nf3 = nf*(fg**2)
	
	with tf.device(device):
		initializer = tf.contrib.layers.variance_scaling_initializer()
		Wgap = tf.get_variable('Wfc', shape=[nf3*(mo+1),opt['n_classes']],
									  initializer=initializer)
		bgap = tf.get_variable('bfc', shape=[opt['n_classes']],
									  initializer=tf.constant_initializer(1e-2))

		x = tf.reshape(x, shape=[bs,opt['dim'],opt['dim'],1,1,opt['n_channels']])
	
	activations = []
	
	# Convolutional Layers
	res1 = hn_lite.conv2d(x, nf, fs, max_order=mo, padding='SAME', name='in', device=device)
	for i in xrange(N):
		name = 'r1_'+str(i)
		res1 = hn_lite.residual_block(res1, nf1, fs, 2, train_phase, max_order=mo, stddev=sm, name=name, device=device)
	res2 = hn_lite.mean_pool(res1, ksize=(1,2,2,1), strides=(1,2,2,1), name='mp1')
	activations.append(res2)
	
	for i in xrange(N):
		name = 'r2_'+str(i)
		res2 = hn_lite.residual_block(res2, nf2, fs, 2, train_phase, max_order=mo, stddev=sm, name=name, device=device)
	res3 = hn_lite.mean_pool(res2, ksize=(1,2,2,1), strides=(1,2,2,1), name='mp2')
	activations.append(res3)
	
	for i in xrange(N):
		name = 'r3_'+str(i)
		res3 = hn_lite.residual_block(res3, nf3, fs, 2, train_phase, max_order=mo, stddev=sm, name=name, device=device)
	#res4 = hn_lite.mean_pool(res3, ksize=(1,2,2,1), strides=(1,2,2,1), name='mp3')
	res4 = res3
	activations.append(res4)

	with tf.name_scope('gap') as scope:
		#gap = tf.reduce_mean(hn_lite.sum_magnitudes(res4), reduction_indices=[1,2,3,4])
		mags = hn_lite.stack_magnitudes(res4, keep_dims=False)
		gap = tf.reduce_mean(mags, reduction_indices=[1,2])
		gapsh = gap.get_shape().as_list()
		gap = tf.reshape(gap, tf.pack([gapsh[0],-1]))
		return tf.nn.bias_add(tf.matmul(gap, Wgap), bgap)


def deep_bsd(opt, x, train_phase, device='/cpu:0'):
	"""High frequency convolutions are unstable, so get rid of them"""
	# Sure layers weight & bias
	order = 1
	nf = int(opt['n_filters'])
	nf2 = int((opt['filter_gain'])*nf)
	nf3 = int((opt['filter_gain']**2)*nf)
	nf4 = int((opt['filter_gain']**3)*nf)
	bs = opt['batch_size']
	fs = opt['filter_size']
	nch = opt['n_channels']
	ncl = opt['n_classes']
	tp = train_phase
	d = device
	
	sm = opt['std_mult']
	with tf.device(d):
		bias = tf.get_variable('fuse', shape=[1],
							   initializer=tf.constant_initializer(1e-2))
		
		side_weights = {
			'sw1' : tf.get_variable('sw1', shape=[1,1,(order+1)*nf,1],
									initializer=tf.constant_initializer(1e-2)),
			'sw2' : tf.get_variable('sw2', shape=[1,1,(order+1)*nf2,1],
									initializer=tf.constant_initializer(1e-2)),
			'sw3' : tf.get_variable('sw3', shape=[1,1,(order+1)*nf3,1],
									initializer=tf.constant_initializer(1e-2)),
			'sw4' : tf.get_variable('sw4', shape=[1,1,(order+1)*nf4,1],
									initializer=tf.constant_initializer(1e-2)),
			'sw5' : tf.get_variable('sw5', shape=[1,1,(order+1)*nf4,1],
									initializer=tf.constant_initializer(1e-2)),
			'h1' : tf.get_variable('h1', shape=[1,1,5,1],
								   initializer=tf.constant_initializer(1e-2))
		}
		fm = {}
		cv = {}
		
	# Convolutional Layers
	with tf.name_scope('stage1') as scope:
		cv1 = h_conv(x, [fs,fs,nch,nf], name='1_1', device=d)
		cv1 = h_nonlin(cv1, tf.nn.relu, name='1_1', device=d)
	
		cv2 = h_conv(cv1, [fs,fs,nf,nf], name='1_2', device=d)
		cv2 = h_batch_norm(cv2, tf.nn.relu, tp, name='bn1', device=d)
		fm[1] = conv2d(stack_magnitudes(cv2), side_weights['sw1']) 
		cv[1] = cv2
	
	with tf.name_scope('stage2') as scope:
		cv3 = mean_pooling(cv2, ksize=(1,2,2,1), strides=(1,2,2,1))
		cv3 = h_conv(cv3, [fs,fs,nf,nf2], name='2_1', device=d)
		cv3 = h_nonlin(cv3, tf.nn.relu, name='2_1', device=d)
	
		cv4 = h_conv(cv3, [fs,fs,nf2,nf2], name='2_2', device=d)
		cv4 = h_batch_norm(cv4, tf.nn.relu, train_phase, name='bn2', device=d)
		fm[2] = conv2d(stack_magnitudes(cv4), side_weights['sw2']) 
		cv[2] = cv4
		
	with tf.name_scope('stage3') as scope:
		cv5 = mean_pooling(cv4, ksize=(1,2,2,1), strides=(1,2,2,1))
		cv5 = h_conv(cv5, [fs,fs,nf2,nf3], name='3_1', device=d)
		cv5 = h_nonlin(cv5, tf.nn.relu, name='3_1', device=d)
	
		cv6 = h_conv(cv5, [fs,fs,nf3,nf3], name='3_2', device=d)
		cv6 = h_batch_norm(cv6, tf.nn.relu, train_phase, name='bn3', device=d)
		fm[3] = conv2d(stack_magnitudes(cv6), side_weights['sw3']) 
		cv[3] = cv6
		
	with tf.name_scope('stage4') as scope:
		cv7 = mean_pooling(cv6, ksize=(1,2,2,1), strides=(1,2,2,1))
		cv7 = h_conv(cv7, [fs,fs,nf3,nf4], name='4_1', device=d)
		cv7 = h_nonlin(cv7, tf.nn.relu, name='4_1', device=d)
	
		cv8 = h_conv(cv7, [fs,fs,nf4,nf4], name='4_2', device=d)
		cv8 = h_batch_norm(cv8, tf.nn.relu, train_phase, name='bn4', device=d)
		fm[4] = conv2d(stack_magnitudes(cv8), side_weights['sw4']) 
		cv[4] = cv8
		
	with tf.name_scope('stage5') as scope:
		cv9 = mean_pooling(cv8, ksize=(1,2,2,1), strides=(1,2,2,1))
		cv9 = h_conv(cv9, [fs,fs,nf4,nf4], name='5_1', device=d)
		cv9 = h_nonlin(cv9, tf.nn.relu, name='5_1', device=d)
	
		cv10 = h_conv(cv9, [fs,fs,nf4,nf4], name='5_2', device=d)
		cv10 = h_batch_norm(cv10, tf.nn.relu, train_phase, name='bn5', device=d)
		fm[5] = conv2d(stack_magnitudes(cv10), side_weights['sw5']) 
		cv[5] = cv10
		
		out = 0
	
	fms = {}
	side_preds = []
	xsh = tf.shape(x)
	with tf.name_scope('fusion') as scope:
		for key in fm.keys():
			if opt['machine'] == 'grumpy':
				fms[key] = tf.image.resize_images(fm[key], tf.pack([xsh[1], xsh[2]]))
			else:
				fms[key] = tf.image.resize_images(fm[key], xsh[1], xsh[2])
			side_preds.append(fms[key])
		side_preds = tf.concat(3, side_preds)

		fms['fuse'] = conv2d(side_preds, side_weights['h1'], b=bias, padding='SAME')
		return fms, out, weights, psis, cv
