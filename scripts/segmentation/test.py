import os
from tqdm import tqdm
import numpy as np

import mxnet as mx
from mxnet import gluon
from mxnet.gluon.data.vision import transforms

from gluoncv.utils import PolyLRScheduler
from gluoncv.model_zoo.segbase import *
from gluoncv.model_zoo import get_model
from gluoncv.data import get_segmentation_dataset, ms_batchify_fn
from gluoncv.utils.viz import get_color_pallete
from gluoncv.utils.metrics.voc_segmentation import batch_pix_accuracy, batch_intersection_union

from train import parse_args

def test(args):
    # output folder
    outdir = 'outdir'
    if not os.path.exists(outdir):
        os.makedirs(outdir)
    # image transform
    input_transform = transforms.Compose([
        transforms.ToTensor(),
        transforms.Normalize([.485, .456, .406], [.229, .224, .225]),
    ])
    # dataset and dataloader
    if args.eval:
        testset = get_segmentation_dataset(
            args.dataset, split='val', mode='testval', transform=input_transform)
        total_inter, total_union, total_correct, total_label = \
            np.int64(0), np.int64(0), np.int64(0), np.int64(0)
    else:
        testset = get_segmentation_dataset(
            args.dataset, split='test', mode='test', transform=input_transform)
    test_data = gluon.data.DataLoader(
        testset, args.test_batch_size, last_batch='keep',
        batchify_fn=ms_batchify_fn, num_workers=args.workers)
    # create network
    if args.model_zoo is not None:
        model = get_model(args.model_zoo, pretrained=True)
    else:
        model = get_segmentation_model(model=args.model, dataset=args.dataset, ctx = args.ctx,
                                       backbone=args.backbone, norm_layer=args.norm_layer)
        # load pretrained weight
        assert args.resume is not None, '=> Please provide the checkpoint using --resume'
        if os.path.isfile(args.resume):
            model.load_params(args.resume, ctx=args.ctx)
        else:
            raise RuntimeError("=> no checkpoint found at '{}'" \
                .format(args.resume))
    print(model)
    evaluator = MultiEvalModel(model, testset.num_class, ctx_list=args.ctx)

    tbar = tqdm(test_data)
    for i, (data, dsts) in enumerate(tbar):
        if args.eval:
            targets = dsts
            predicts = evaluator.parallel_forward(data)
            for predict, target in zip(predicts, targets):
                target = target.as_in_context(predict[0].context)
                correct, labeled = batch_pix_accuracy(predict[0], target)
                inter, union = batch_intersection_union(
                    predict[0], target, testset.num_class)
                total_correct += correct.astype('int64')
                total_label += labeled.astype('int64')
                total_inter += inter.astype('int64')
                total_union += union.astype('int64')
            pixAcc = np.float64(1.0) * total_correct / (np.spacing(1, dtype=np.float64) + total_label)
            IoU = np.float64(1.0) * total_inter / (np.spacing(1, dtype=np.float64) + total_union)
            mIoU = IoU.mean()
            tbar.set_description(
                'pixAcc: %.4f, mIoU: %.4f' % (pixAcc, mIoU))
        else:
            im_paths = dsts
            predicts = evaluator.parallel_forward(data)
            for predict, impath in zip(predicts, im_paths):
                predict = mx.nd.squeeze(mx.nd.argmax(predict[0], 1)).asnumpy()
                mask = get_color_pallete(predict, args.dataset)
                outname = os.path.splitext(impath)[0] + '.png'
                mask.save(os.path.join(outdir, outname))

if __name__ == "__main__":
    args = parse_args()
    args.test_batch_size = args.ngpus
    print('Testing model: ', args.resume)
    test(args)
