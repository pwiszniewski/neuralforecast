# AUTOGENERATED! DO NOT EDIT! File to edit: ../../nbs/common.base_model.ipynb.

# %% auto 0
__all__ = ['BaseModel']

# %% ../../nbs/common.base_model.ipynb 2
import inspect
import random
import warnings
from copy import deepcopy

import numpy as np
import torch
import pytorch_lightning as pl

from ..tsdataset import TimeSeriesDataModule

# %% ../../nbs/common.base_model.ipynb 3
class BaseModel(pl.LightningModule):
    def __init__(self):
        super().__init__()

    def __repr__(self):
        return type(self).__name__ if self.alias is None else self.alias

    def _check_exog(self, dataset):
        temporal_cols = set(dataset.temporal_cols.tolist())
        static_cols = set(
            dataset.static_cols.tolist() if dataset.static_cols is not None else []
        )

        missing_hist = set(self.hist_exog_list) - temporal_cols
        missing_futr = set(self.futr_exog_list) - temporal_cols
        missing_stat = set(self.stat_exog_list) - static_cols
        if missing_hist:
            raise Exception(
                f"{missing_hist} historical exogenous variables not found in input dataset"
            )
        if missing_futr:
            raise Exception(
                f"{missing_futr} future exogenous variables not found in input dataset"
            )
        if missing_stat:
            raise Exception(
                f"{missing_stat} static exogenous variables not found in input dataset"
            )

    def _restart_seed(self, random_seed):
        if random_seed is None:
            random_seed = self.random_seed
        torch.manual_seed(random_seed)

    def _get_temporal_exogenous_cols(self, temporal_cols):
        return list(
            set(temporal_cols.tolist()) & set(self.hist_exog_list + self.futr_exog_list)
        )

    def _fit(
        self,
        dataset,
        batch_size,
        valid_batch_size=1024,
        val_size=0,
        test_size=0,
        random_seed=None,
        shuffle_train=True,
    ):
        self._check_exog(dataset)
        self._restart_seed(random_seed)

        self.val_size = val_size
        self.test_size = test_size
        datamodule = TimeSeriesDataModule(
            dataset=dataset,
            batch_size=batch_size,
            valid_batch_size=valid_batch_size,
            num_workers=self.num_workers_loader,
            drop_last=self.drop_last_loader,
            shuffle_train=shuffle_train,
        )

        if self.val_check_steps > self.max_steps:
            warnings.warn(
                "val_check_steps is greater than max_steps, \
                    setting val_check_steps to max_steps"
            )
        val_check_interval = min(self.val_check_steps, self.max_steps)
        self.trainer_kwargs["val_check_interval"] = int(val_check_interval)
        self.trainer_kwargs["check_val_every_n_epoch"] = None

        trainer = pl.Trainer(**self.trainer_kwargs)
        trainer.fit(self, datamodule=datamodule)
        return trainer

    def on_fit_start(self):
        torch.manual_seed(self.random_seed)
        np.random.seed(self.random_seed)
        random.seed(self.random_seed)

    def configure_optimizers(self):
        if self.optimizer:
            optimizer_signature = inspect.signature(self.optimizer)
            optimizer_kwargs = deepcopy(self.optimizer_kwargs)
            if "lr" in optimizer_signature.parameters:
                if "lr" in optimizer_kwargs:
                    warnings.warn(
                        "ignoring learning rate passed in optimizer_kwargs, using the model's learning rate"
                    )
                optimizer_kwargs["lr"] = self.learning_rate
            optimizer = self.optimizer(params=self.parameters(), **optimizer_kwargs)
        else:
            optimizer = torch.optim.Adam(self.parameters(), lr=self.learning_rate)
        scheduler = {
            "scheduler": torch.optim.lr_scheduler.StepLR(
                optimizer=optimizer, step_size=self.lr_decay_steps, gamma=0.5
            ),
            "frequency": 1,
            "interval": "step",
        }
        return {"optimizer": optimizer, "lr_scheduler": scheduler}

    def get_test_size(self):
        return self.test_size

    def set_test_size(self, test_size):
        self.test_size = test_size

    def on_validation_epoch_end(self):
        if self.val_size == 0:
            return
        avg_loss = torch.stack(self.validation_step_outputs).mean()
        self.log("ptl/val_loss", avg_loss)
        self.valid_trajectories.append((self.global_step, float(avg_loss)))
        self.validation_step_outputs.clear()  # free memory (compute `avg_loss` per epoch)

    def save(self, path):
        self.trainer.save_checkpoint(path)