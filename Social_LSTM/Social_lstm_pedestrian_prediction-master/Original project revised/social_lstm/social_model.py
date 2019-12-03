    # coding:utf-8

'''
Social LSTM model implementation using Tensorflow
Social LSTM Paper: http://vision.stanford.edu/pdf/CVPR16_N_LSTM.pdf

Author : Anirudh Vemula
Date: 17th October 2016
'''

import tensorflow as tf
import numpy as np
from tensorflow.python.ops import rnn_cell
from grid import getSequenceGridMask
import ipdb


class SocialModel():

    def __init__(self, args, infer=False):
        '''
        Initialisation function for the class SocialModel
        params:
        args : Contains arguments required for the model creation
        '''

        # If sampling new trajectories, then infer mode
        if infer:        #QUESTION: 这一步有什么用？
            # Sample one position at a time
            args.batch_size = 1
            args.seq_length = 1

        # Store the arguments
        self.args = args
        self.infer = infer
        # Store rnn size and grid_size
        self.rnn_size = args.rnn_size   #QUESTION： rnn size是什么。 是hidden state的维度吗？
        self.grid_size = args.grid_size

        # Maximum number of peds
        self.maxNumPeds = args.maxNumPeds

        # NOTE : For now assuming, batch_size is always 1. That is the input
        # to the model is always a sequence of frames
        #现在假设，batch_size始终为1。也就是说，模型的输入始终为帧序列

        #自己加的
        #tf.reset_default_graph() # To clear the defined variables and operations of the previous cell

        with tf.Session() as sess:

            # Construct the basicLSTMCell recurrent unit with a dimension given by args.rnn_size
            with tf.name_scope("LSTM_cell"):  #QUESTION: rnn_size到底是什么
                cell = rnn_cell.BasicLSTMCell(args.rnn_size, state_is_tuple=False)   #def __init__(self,num_units,forget_bias=1.0,......）
                # if not infer and args.keep_prob < 1:
                # cell = rnn_cell.DropoutWrapper(cell, output_keep_prob=args.keep_prob)

            # placeholders for the input data and the target data
            # A sequence contains an ordered set of consecutive frames
            # Each frame can contain a maximum of 'args.maxNumPeds' number of peds
            # For each ped we have their (pedID, x, y) positions as input
            self.input_data = tf.placeholder(tf.float32, [args.seq_length, args.maxNumPeds, 3], name="input_data")

            # target data would be the same format as input_data except with
            # one time-step ahead
            self.target_data = tf.placeholder(tf.float32, [args.seq_length, args.maxNumPeds, 3], name="target_data")

            # Grid data would be a binary matrix which encodes whether a pedestrian is present in
            # a grid cell of other pedestrian
            self.grid_data = tf.placeholder(tf.float32, [args.seq_length, args.maxNumPeds, args.maxNumPeds, args.grid_size*args.grid_size], name="grid_data")

            # Variable to hold the value of the learning rate
            self.lr = tf.Variable(args.learning_rate, trainable=False, name="learning_rate")

            # Output dimension of the model
            self.output_size = 5

            # Define embedding and output layers
            self.define_embedding_and_output_layers(args)

            # Define LSTM states for each pedestrian
            with tf.variable_scope("initial_LSTM_states"):
                self.LSTM_states = tf.zeros([args.maxNumPeds, cell.state_size], name="LSTM_states")    #state_size 此时是256.  之前好像说了是rnn_size的两倍#QUESTION
                # Nella versione di tf<1.0 era :self.initial_states = tf.split(0, args.maxNumPeds, self.LSTM_states)
                self.initial_states = tf.split(self.LSTM_states, args.maxNumPeds, 0 )   #是一个长度为 arg.maxNumPeds 的list,list中每个元素是某个行人的LSTM state
                #self.LSTM_states.shape=(args.maxNumpeds,256),,,,256为128*2   #QUESTION：跟是不是tuple有关系

            # Define hidden output states for each pedestrian
            with tf.variable_scope("Hidden_states"):
                # Nella versione di tf<1.0 era : self.output_states = tf.split(0, args.maxNumPeds, tf.zeros([args.maxNumPeds, cell.output_size]))
                self.output_states = tf.split(tf.zeros([args.maxNumPeds, cell.output_size]), args.maxNumPeds,0 )  #变成了maxNumPeds个【1,cell_output_size】


            # List of tensors each of shape args.maxNumPedsx3 corresponding to each frame in the sequence
            with tf.name_scope("frame_data_tensors"):
                # Nella versione di tf<1.0 era : frame_data = [tf.squeeze(input_, [0]) for input_ in tf.split(0, args.seq_length, self.input_data)]
                #frame_data is a list.
                frame_data = [tf.squeeze(input_, [0]) for input_ in tf.split(self.input_data, args.seq_length, 0)]   #len(frame_data)=args.seq_length


            #QUESTION: 问题就出在这里。调试的时候显示frame_data=20.而运行的时候frame=19时就出现问题。说明frame=20后的数据有问题。
            #数据没有问题。是因为arg里面就定义了seq_length是20

            with tf.name_scope("frame_target_data_tensors"):
                # Nella versione di tf<1.0 era : frame_target_data = [tf.squeeze(target_, [0]) for target_ in tf.split(0, args.seq_length, self.target_data)]
                frame_target_data = [tf.squeeze(target_, [0]) for target_ in tf.split(self.target_data, args.seq_length, 0)]

            with tf.name_scope("grid_frame_data_tensors"):
                # This would contain a list of tensors each of shape MNP x MNP x (GS**2) encoding the mask
                # Nella versione di tf<1.0 era : grid_frame_data = [tf.squeeze(input_, [0]) for input_ in tf.split(0, args.seq_length, self.grid_data)]
                grid_frame_data = [tf.squeeze(input_, [0]) for input_ in tf.split(self.grid_data, args.seq_length, 0)]

            # Cost   #QUESTION： 下面这三个东西有什么用
            #统计所有帧内，所有行人的cost的总和
            with tf.name_scope("Cost_related_stuff"):
                self.cost = tf.constant(0.0, name="cost")
                self.counter = tf.constant(0.0, name="counter")
                self.increment = tf.constant(1.0, name="increment")

            # Containers to store output distribution parameters
            with tf.name_scope("Distribution_parameters_stuff"):
                # Nella versione di tf<1.0 era self.initial_output = tf.split(0, args.maxNumPeds, tf.zeros([args.maxNumPeds, self.output_size]))
                self.initial_output = tf.split(tf.zeros([args.maxNumPeds, self.output_size]), args.maxNumPeds, 0 )

            # Tensor to represent non-existent ped
            with tf.name_scope("Non_existent_ped_stuff"):
                nonexistent_ped = tf.constant(0.0, name="zero_ped")

            # Iterate over each frame in the sequence
            for seq, frame in enumerate(frame_data):
                print "Frame number", seq

                current_frame_data = frame  # MNP x 3 tensor
                current_grid_frame_data = grid_frame_data[seq]  # MNP x MNP x (GS**2) tensor
                social_tensor = self.getSocialTensor(current_grid_frame_data, self.output_states)  # MNP x (GS**2 * RNN_size)
                # NOTE: Using a tensor of zeros as the social tensor
                # social_tensor = tf.zeros([args.maxNumPeds, args.grid_size*args.grid_size*args.rnn_size])

                with tf.name_scope("Frames"):

                    for ped in range(args.maxNumPeds):
                        print "Pedestrian Number", ped


                        # pedID of the current pedestrian
                        pedID = current_frame_data[ped, 0]

                        with tf.name_scope("extract_input_ped"):
                            # Extract x and y positions of the current ped of current frame
                            self.spatial_input = tf.slice(current_frame_data, [ped, 1], [1, 2])  # Tensor of shape (1,2)
                            # Extract the social tensor of the current ped
                            self.tensor_input = tf.slice(social_tensor, [ped, 0], [1, args.grid_size*args.grid_size*args.rnn_size])  # Tensor of shape (1, g*g*r)


                        with tf.name_scope("embeddings_operations"):
                            #self.spatial_input.shape=(1,2),self.embedding_w.shape=(2,64)
                            # Embed the spatial input
                            embedded_spatial_input = tf.nn.relu(tf.nn.xw_plus_b(self.spatial_input, self.embedding_w, self.embedding_b))
                            # Embed the tensor input
                            embedded_tensor_input = tf.nn.relu(tf.nn.xw_plus_b(self.tensor_input, self.embedding_t_w, self.embedding_t_b))
                            #embedded_spatial_input.shape=(1,64); embedded_tensor_input.shape=(1,64)


                        with tf.name_scope("concatenate_embeddings"):
                            # Concatenate the embeddings
                            # Nella versione di tf<1.0 era : complete_input = tf.concat(1, [embedded_spatial_input, embedded_tensor_input])
                            complete_input = tf.concat([embedded_spatial_input, embedded_tensor_input], 1)
                            #complete_input =(1,128)

                        # One step of LSTM   #为某个行人 更新状态。
                        with tf.variable_scope("reused_LSTM") as scope:
                            if seq > 0 or ped > 0:
                                scope.reuse_variables()                #ATTENTION
                            self.output_states[ped], self.initial_states[ped] = cell(complete_input, self.initial_states[ped])
                            #len(output_states)=maxNumPeds=70       self.output_states[ped].shape=（1，rnn_size）=（1，128）
                            #self.initial_states[ped].shape=(1,256)


                        # with tf.name_scope("reshape_output"):
                        # Store the output hidden state for the current pedestrian
                        #    self.output_states[ped] = tf.reshape(tf.concat(1, output), [-1, args.rnn_size])
                        #    print self.output_states[ped]

                        # Apply the linear layer. Output would be a tensor of shape 1 x output_size
                        with tf.name_scope("output_linear_layer"):
                            self.initial_output[ped] = tf.nn.xw_plus_b(self.output_states[ped], self.output_w, self.output_b)
                            #self.output_states[ped].shape=（1,5）

                        # with tf.name_scope("store_distribution_parameters"):
                        #    # Store the distribution parameters for the current ped
                        #    self.initial_output[ped] = output

                        with tf.name_scope("extract_target_ped"):
                            # Extract x and y coordinates of the target data
                            # x_data and y_data would be tensors of shape 1 x 1
                            # Nella versione di tf<1.0 era : [x_data, y_data] = tf.split(1, 2, tf.slice(frame_target_data[seq], [ped, 1], [1, 2]))
                            [x_data, y_data] = tf.split(tf.slice(frame_target_data[seq], [ped, 1], [1, 2]), 2, 1)
                            target_pedID = frame_target_data[seq][ped, 0]

                        with tf.name_scope("get_coef"):   #QUESTION： 为什么要对输出做非线性变换？
                            # Extract coef from output of the linear output layer
                            [o_mux, o_muy, o_sx, o_sy, o_corr] = self.get_coef(self.initial_output[ped])

                        with tf.name_scope("calculate_loss"):
                            # Calculate loss for the current ped
                            lossfunc = self.get_lossfunc(o_mux, o_muy, o_sx, o_sy, o_corr, x_data, y_data)

                        with tf.name_scope("increment_cost"):
                            # If it is a non-existent ped, it should not contribute to cost
                            # If the ped doesn't exist in the next frame, he/she should not contribute to cost as well

                            # Nella versione di tf<1.0 era : self.cost = tf.select(tf.logical_or(tf.equal(pedID, nonexistent_ped), tf.equal(target_pedID, nonexistent_ped)), self.cost, tf.add(self.cost, lossfunc))
                            #tf.where(): 返回值：如果x、y不为空的话，返回值和x、y有相同的形状，如果condition对应位置值为True那么返回Tensor对应位置为x的值，否则为y的值.
                            self.cost = tf.where(
                                tf.logical_or(tf.equal(pedID, nonexistent_ped), tf.equal(target_pedID, nonexistent_ped)),self.cost, tf.add(self.cost, lossfunc))   #如果当前的新人有与之相应的target，则计算cost

                            # Nella versione di tf<1.0 era : self.counter = tf.select(tf.logical_or(tf.equal(pedID, nonexistent_ped), tf.equal(target_pedID, nonexistent_ped)), self.counter, tf.add(self.counter, self.increment))
                            self.counter = tf.where(
                                tf.logical_or(tf.equal(pedID, nonexistent_ped), tf.equal(target_pedID, nonexistent_ped)),
                                self.counter, tf.add(self.counter, self.increment))



            with tf.name_scope("mean_cost"):
                # Mean of the cost
                self.cost = tf.div(self.cost, self.counter)

            # Get all trainable variables
            '''
            embedding_layer/coordinate_embedding/embedding_w   shape=(2, 64)
            embedding_layer/coordinate_embedding/embedding_b   shape=(64,)
            embedding_layer/tensor_embedding/embedding_t_w     shape=(2048, 64)
            embedding_layer/tensor_embedding/embedding_t_b     shape=(64,)
            embedding_layer/output_layer/output_w              shape=(128, 5)
            embedding_layer/output_layer/output_b              shape=(5,)
            LSTM/basic_lstm_cell/kernel                        shape=(256, 512)
            LSTM/basic_lstm_cell/bias                          shape=(512,)    
            
            共8个可训练的变量
            '''
            tvars = tf.trainable_variables()   #返回的是所有变量的列表




            # L2 loss
            l2 = args.lambda_param*sum(tf.nn.l2_loss(tvar) for tvar in tvars)
            self.cost = self.cost + l2

            # Get the final LSTM states
            # Nella versione di tf<1.0 era : self.final_states = tf.concat(0, self.initial_states)
            self.final_states = tf.concat(self.initial_states, 0)
            #self.final_states.shape=(70,256)   len(self.initial_states)=70   list里面的元素是（1，256）


            # Get the final distribution parameters
            self.final_output = self.initial_output

            # Compute gradients
            self.gradients = tf.gradients(self.cost, tvars)         #ATTENTION：实现self.cost对tvars求导

            # Clip the gradients
            grads, _ = tf.clip_by_global_norm(self.gradients, args.grad_clip)  #让权重的更新限制在一个合适的范围
            #QUESTION： 这个 _  是什么

            # Define the optimizer
            optimizer = tf.train.RMSPropOptimizer(self.lr)

            # The train operator
            self.train_op = optimizer.apply_gradients(zip(grads, tvars))     #zip() 函数用于将可迭代的对象作为参数，将对象中对应的元素
                                                                             #打包成一个个元组，然后返回由这些元组组成的列表。
            #instrument tensorboard
            writer = tf.summary.FileWriter("/home/jwei/tensorboard_events/", sess.graph)
            writer.add_graph(sess.graph)


            # Merge all summmaries
            # merged_summary_op = tf.merge_all_summaries()

    #ATTENTION：注意此处，在variable_scope中使用了get_variable来创建变量，因此后面要对参数进行训练时，可以调用之前已经训练过的数据
    def define_embedding_and_output_layers(self, args):
        with tf.variable_scope("embedding_layer"):
        # Define variables for the spatial coordinates embedding layer
            with tf.variable_scope("coordinate_embedding"):
                self.embedding_w = tf.get_variable("embedding_w", [2, args.embedding_size], initializer=tf.truncated_normal_initializer(stddev=0.1))
                self.embedding_b = tf.get_variable("embedding_b", [args.embedding_size], initializer=tf.constant_initializer(0.1))

            # Define variables for the social tensor embedding layer
            with tf.variable_scope("tensor_embedding"):
                self.embedding_t_w = tf.get_variable("embedding_t_w", [args.grid_size*args.grid_size*args.rnn_size, args.embedding_size], initializer=tf.truncated_normal_initializer(stddev=0.1))
                self.embedding_t_b = tf.get_variable("embedding_t_b", [args.embedding_size], initializer=tf.constant_initializer(0.1))

            # Define variables for the output linear layer
            with tf.variable_scope("output_layer"):
                self.output_w = tf.get_variable("output_w", [args.rnn_size, self.output_size], initializer=tf.truncated_normal_initializer(stddev=0.1))
                self.output_b = tf.get_variable("output_b", [self.output_size], initializer=tf.constant_initializer(0.1))

    def tf_2d_normal(self, x, y, mux, muy, sx, sy, rho):
        '''
        Function that implements the PDF of a 2D normal distribution
        params:
        x : input x points
        y : input y points
        mux : mean of the distribution in x
        muy : mean of the distribution in y
        sx : std dev of the distribution in x
        sy : std dev of the distribution in y
        rho : Correlation factor of the distribution
        '''
        # eq 3 in the paper
        # and eq 24 & 25 in Graves (2013)
        # Calculate (x - mux) and (y-muy)
        # Nella versione di tf<1.0 era : normx = tf.sub(x, mux)
        normx = tf.subtract(x, mux)
        # Nella versione di tf<1.0 era : normy = tf.sub(y, muy)
        normy = tf.subtract(y, muy)

        # Calculate sx*sy
        # Nella versione di tf<1.0 era : sxsy = tf.mul(sx, sy)
        sxsy = tf.multiply(sx, sy)

        # Calculate the exponential factor
        # Nella versione di tf<1.0 era : z = tf.square(tf.div(normx, sx)) + tf.square(tf.div(normy, sy)) - 2*tf.div(tf.mul(rho, tf.mul(normx, normy)), sxsy)
        z = tf.square(tf.div(normx, sx)) + tf.square(tf.div(normy, sy)) - 2 * tf.div(tf.multiply(rho, tf.multiply(normx, normy)),sxsy)
        negRho = 1 - tf.square(rho)
        # Numerator
        result = tf.exp(tf.div(-z, 2*negRho))

        # Normalization constant
        # Nella versione di tf<1.0 era : denom = 2 * np.pi * tf.mul(sxsy, tf.sqrt(negRho))
        denom = 2 * np.pi * tf.multiply(sxsy, tf.sqrt(negRho))

        # Final PDF calculation
        result = tf.div(result, denom)
        return result

    def get_lossfunc(self, z_mux, z_muy, z_sx, z_sy, z_corr, x_data, y_data):
        '''
        Function to calculate given a 2D distribution over x and y, and target data
        of observed x and y points
        params:
        z_mux : mean of the distribution in x
        z_muy : mean of the distribution in y
        z_sx : std dev of the distribution in x
        z_sy : std dev of the distribution in y
        z_rho : Correlation factor of the distribution
        x_data : target x points
        y_data : target y points
        '''
        # step = tf.constant(1e-3, dtype=tf.float32, shape=(1, 1))

        # Calculate the PDF of the data w.r.t to the distribution
        result0 = self.tf_2d_normal(x_data, y_data, z_mux, z_muy, z_sx, z_sy, z_corr)   #target在输出值（符合正态分布）里的概率

        # For numerical stability purposes
        epsilon = 1e-20

        # Apply the log operation
        result1 = -tf.log(tf.maximum(result0, epsilon))  # Numerical stability
        #result1.shape=(1,1)


        # Sum up all log probabilities for each data point
        return tf.reduce_sum(result1)          #QUESTION: result1只是个（1，1）的tensor，需要这个reduce_sum吗

    def get_coef(self, output):
        # eq 20 -> 22 of Graves (2013)

        z = output
        # Split the output into 5 parts corresponding to means, std devs and corr
        # Nella versione di tf<1.0 era : z_mux, z_muy, z_sx, z_sy, z_corr = tf.split(1, 5, z)
        z_mux, z_muy, z_sx, z_sy, z_corr = tf.split(z, 5, 1)  #将[o_mux, o_muy, o_sx, o_sy, o_corr]拆开成5个（1，1）的Tensor

        # The output must be exponentiated for the std devs
        z_sx = tf.exp(z_sx)      #QUESTION： 为什么要求指数？    可能是计算loss的公式需要？
        z_sy = tf.exp(z_sy)
        # Tanh applied to keep it in the range [-1, 1]
        z_corr = tf.tanh(z_corr)

        return [z_mux, z_muy, z_sx, z_sy, z_corr]

    def getSocialTensor(self, grid_frame_data, output_states):
        '''
        Computes the social tensor for all the maxNumPeds in the frame
        params:
        grid_frame_data : A tensor of shape MNP x MNP x (GS**2)
        output_states : A list of tensors each of shape 1 x RNN_size of length MNP
        '''
        # Create a zero tensor of shape MNP x (GS**2) x RNN_size
        social_tensor = tf.zeros([self.args.maxNumPeds, self.grid_size*self.grid_size, self.rnn_size], name="social_tensor")

        # Create a list of zero tensors each of shape 1 x (GS**2) x RNN_size of length MNP
        # Nella versione di tf<1.0 era : social_tensor = tf.split(0, self.args.maxNumPeds, social_tensor)
        social_tensor = tf.split(social_tensor, self.args.maxNumPeds, 0)

        # Concatenate list of hidden states to form a tensor of shape MNP x RNN_size
        # Nella versione di tf<1.0 era : hidden_states = tf.concat(0, output_states)
        hidden_states = tf.concat(output_states, 0)
        #hidden_states.shape=(70,128)=(MNP,rnn_size)

        with tf.name_scope("calculate_social_tensor"):

            # Split the grid_frame_data into grid_data for each pedestrians
            # Consists of a list of tensors each of shape 1 x MNP x (GS**2) of length MNP
            # Nella versione di tf<1.0 era : grid_frame_ped_data = tf.split(0, self.args.maxNumPeds, grid_frame_data)
            grid_frame_ped_data = tf.split(grid_frame_data, self.args.maxNumPeds, 0)

            # Squeeze tensors to form MNP x (GS**2) matrices
            grid_frame_ped_data = [tf.squeeze(input_, [0]) for input_ in grid_frame_ped_data]

            # For each pedestrian
            for ped in range(self.args.maxNumPeds):
                # Compute social tensor for the current pedestrian
                with tf.name_scope("tensor_calculation"):
                    social_tensor_ped = tf.matmul(tf.transpose(grid_frame_ped_data[ped]), hidden_states)
                    social_tensor[ped] = tf.reshape(social_tensor_ped, [1, self.grid_size*self.grid_size, self.rnn_size])

            # Concatenate the social tensor from a list to a tensor of shape MNP x (GS**2) x RNN_size
            # Nella versione di tf<1.0 era :  social_tensor = tf.concat(0, social_tensor)
            social_tensor = tf.concat(social_tensor, 0)

            # Reshape the tensor to match the dimensions MNP x (GS**2 * RNN_size)
            social_tensor = tf.reshape(social_tensor, [self.args.maxNumPeds, self.grid_size*self.grid_size*self.rnn_size])
            return social_tensor


    def sample_gaussian_2d(self, mux, muy, sx, sy, rho):
        '''
        Function to sample a point from a given 2D normal distribution
        params:
        mux : mean of the distribution in x
        muy : mean of the distribution in y
        sx : std dev of the distribution in x
        sy : std dev of the distribution in y
        rho : Correlation factor of the distribution
        '''
        # Extract mean
        mean = [mux, muy]
        # Extract covariance matrix
        cov = [[sx*sx, rho*sx*sy], [rho*sx*sy, sy*sy]]
        # Sample a point from the multivariate normal distribution
        x = np.random.multivariate_normal(mean, cov, 1)

        #Modifica di SIMONE per non utilizzare un numero random per decidere la posizione futura del pedone:
        return mux,muy #era return x[0][0], x[0][1]

    def sample(self, sess, traj, grid, dimensions, true_traj, num=10):
        # traj is a sequence of frames (of length obs_length)
        # so traj shape is (obs_length x maxNumPeds x 3)
        # grid is a tensor of shape obs_length x maxNumPeds x maxNumPeds x (gs**2)
        states = sess.run(self.LSTM_states)
        # print "Fitting"
        # For each frame in the sequence
        for index, frame in enumerate(traj[:-1]):
            data = np.reshape(frame, (1, self.maxNumPeds, 3))
            target_data = np.reshape(traj[index+1], (1, self.maxNumPeds, 3))
            grid_data = np.reshape(grid[index, :], (1, self.maxNumPeds, self.maxNumPeds, self.grid_size*self.grid_size))

            feed = {self.input_data: data, self.LSTM_states: states, self.grid_data: grid_data, self.target_data: target_data}

            [states, cost] = sess.run([self.final_states, self.cost], feed)
            # print cost

        ret = traj

        last_frame = traj[-1]

        prev_data = np.reshape(last_frame, (1, self.maxNumPeds, 3))
        prev_grid_data = np.reshape(grid[-1], (1, self.maxNumPeds, self.maxNumPeds, self.grid_size*self.grid_size))

        prev_target_data = np.reshape(true_traj[traj.shape[0]], (1, self.maxNumPeds, 3))
        # Prediction
        for t in range(num):
            # print "**** NEW PREDICTION TIME STEP", t, "****"
            feed = {self.input_data: prev_data, self.LSTM_states: states, self.grid_data: prev_grid_data, self.target_data: prev_target_data}
            [output, states, cost] = sess.run([self.final_output, self.final_states, self.cost], feed)
            # print "Cost", cost
            # Output is a list of lists where the inner lists contain matrices of shape 1x5. The outer list contains only one element (since seq_length=1) and the inner list contains maxNumPeds elements
            # output = output[0]
            newpos = np.zeros((1, self.maxNumPeds, 3))
            for pedindex, pedoutput in enumerate(output):
                [o_mux, o_muy, o_sx, o_sy, o_corr] = np.split(pedoutput[0], 5, 0)
                mux, muy, sx, sy, corr = o_mux[0], o_muy[0], np.exp(o_sx[0]), np.exp(o_sy[0]), np.tanh(o_corr[0])

                next_x, next_y = self.sample_gaussian_2d(mux, muy, sx, sy, corr)

                #if prev_data[0, pedindex, 0] != 0:
                #     print "Pedestrian ID", prev_data[0, pedindex, 0]
                #     print "Predicted parameters", mux, muy, sx, sy, corr
                #     print "New Position", next_x, next_y
                #     print "Target Position", prev_target_data[0, pedindex, 1], prev_target_data[0, pedindex, 2]
                #     print

                newpos[0, pedindex, :] = [prev_data[0, pedindex, 0], next_x, next_y]
            ret = np.vstack((ret, newpos))
            prev_data = newpos
            prev_grid_data = getSequenceGridMask(prev_data, dimensions, self.args.neighborhood_size, self.grid_size)
            if t != num - 1:
                prev_target_data = np.reshape(true_traj[traj.shape[0] + t + 1], (1, self.maxNumPeds, 3))

        # The returned ret is of shape (obs_length+pred_length) x maxNumPeds x 3
        return ret
