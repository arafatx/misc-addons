# -*- coding: utf-8 -*-

from odoo import models, fields, api
from odoo.tools import html_escape as escape
from odoo.exceptions import Warning as UserError
from odoo.tools.translate import _


SUBTASK_STATES = {'done': 'Done',
                  'todo': 'TODO',
                  'cancelled': 'Cancelled'}


class ProjectTaskSubtask(models.Model):
    _name = "project.task.subtask"
    _inherit = ['ir.needaction_mixin']
    state = fields.Selection([(k, v) for k, v in SUBTASK_STATES.items()],
                             'Status', required=True, copy=False, default='todo')
    name = fields.Char(required=True, string="Description")
    reviewer_id = fields.Many2one('res.users', 'Reviewer', readonly=True, default=lambda self: self.env.user)
    project_id = fields.Many2one("project.project", related='task_id.project_id', store=True)
    user_id = fields.Many2one('res.users', 'Assigned to', required=True)
    task_id = fields.Many2one('project.task', 'Task', ondelete='cascade', required=True, index="1")
    task_state = fields.Char(string='Task state', related='task_id.stage_id.name', readonly=True)
    hide_button = fields.Boolean(compute='_compute_hide_button')
    recolor = fields.Boolean(compute='_compute_recolor')

    @api.multi
    def _compute_recolor(self):
        for record in self:
            if self.env.user == record.user_id and record.state == 'todo':
                record.recolor = True

    @api.multi
    def _compute_hide_button(self):
        for record in self:
            if self.env.user not in [record.reviewer_id, record.user_id]:
                record.hide_button = True

    @api.multi
    def _compute_reviewer_id(self):
        for record in self:
            record.reviewer_id = record.create_uid

    @api.model
    def _needaction_domain_get(self):
        if self._needaction:
            return [('state', '=', 'todo'), ('user_id', '=', self.env.uid)]
        return []

    @api.multi
    def write(self, vals):
        result = super(ProjectTaskSubtask, self).write(vals)
        for r in self:
            if vals.get('state'):
                r.task_id.send_subtask_email(r.name, r.state, r.reviewer_id.id, r.user_id.id)
                if self.env.user != r.reviewer_id and self.env.user != r.user_id:
                    raise UserError(_('Only users related to that subtask can change state.'))
            if vals.get('name'):
                r.task_id.send_subtask_email(r.name, r.state, r.reviewer_id.id, r.user_id.id)
                if self.env.user != r.reviewer_id:
                    raise UserError(_('Only reviewer can change description.'))
            if vals.get('user_id'):
                r.task_id.send_subtask_email(r.name, r.state, r.create_uid.id, r.user_id.id)
        return result

    @api.model
    def create(self, vals):
        result = super(ProjectTaskSubtask, self).create(vals)
        vals = self._add_missing_default_values(vals)
        task = self.env['project.task'].browse(vals.get('task_id'))
        task.send_subtask_email(vals['name'], vals['state'], vals['reviewer_id'], vals['user_id'])
        return result

    @api.multi
    def change_state_done(self):
        for record in self:
            record.state = 'done'

    @api.multi
    def change_state_todo(self):
        for record in self:
            record.state = 'todo'

    @api.multi
    def change_state_cancelled(self):
        for record in self:
            record.state = 'cancelled'


class Task(models.Model):
    _inherit = "project.task"
    subtask_ids = fields.One2many('project.task.subtask', 'task_id', 'Subtask')
    kanban_subtasks = fields.Text(compute='_compute_kanban_subtasks')
    default_user = fields.Many2one('res.users', compute='_compute_default_user')

    @api.multi
    def _compute_default_user(self):
        for record in self:
            if self.env.user != record.user_id and self.env.user != record.create_uid:
                record.default_user = record.user_id
            else:
                if self.env.user != record.user_id:
                    record.default_user = record.user_id
                elif self.env.user != record.create_uid:
                    record.default_user = record.create_uid
                elif self.env.user == record.create_uid and self.env.user == record.user_id:
                    record.default_user = self.env.user

    @api.multi
    def _compute_kanban_subtasks(self):
        for record in self:
            result_string1 = ''
            result_string2 = ''
            result_string3 = ''
            for subtask in record.subtask_ids:
                if subtask.state == 'todo' and record.env.user == subtask.user_id and record.env.user == subtask.reviewer_id:
                    tmp_string3 = escape(u': {0}'.format(subtask.name))
                    result_string3 += u'<li><b>TODO</b>{}</li>'.format(tmp_string3)
                elif subtask.state == 'todo' and record.env.user == subtask.user_id:
                    tmp_string1 = escape(u'{0}: {1}'.format(subtask.reviewer_id.name, subtask.name))
                    result_string1 += u'<li><b>TODO</b> from {}</li>'.format(tmp_string1)
                elif subtask.state == 'todo' and record.env.user == subtask.reviewer_id:
                    tmp_string2 = escape(u'{0}: {1}'.format(subtask.user_id.name, subtask.name))
                    result_string2 += u'<li>TODO for {}</li>'.format(tmp_string2)
            record.kanban_subtasks = '<ul>' + result_string1 + result_string3 + result_string2 + '</ul>'

    @api.multi
    def send_subtask_email(self, subtask_name, subtask_state, subtask_reviewer_id, subtask_user_id):
        for r in self:
            body = ''
            reviewer = self.env["res.users"].browse(subtask_reviewer_id)
            user = self.env["res.users"].browse(subtask_user_id)
            state = SUBTASK_STATES[subtask_state]
            reviewer_ids = []
            subtype = 'project_task_subtask.subtasks_subtype'
            if user == self.env.user and reviewer == self.env.user:
                body = '<p><strong>' + state + '</strong>: ' + escape(subtask_name) + '</p>'
                subtype = False
            elif self.env.user == reviewer:
                body = '<p>' + escape(user.name) + ', <br><strong>' + state + '</strong>: ' + escape(subtask_name) + '</p>'
                reviewer_ids = [user.create_uid.id]
            elif self.env.user == user:
                body = '<p>' + escape(reviewer.name) + ', <br><strong>' + state + '</strong>: ' + escape(subtask_name) + '</p>'
                reviewer_ids = [reviewer.create_uid.id]
            r.message_post(type='comment',
                           subtype=subtype,
                           body=body,
                           reviewer_ids=reviewer_ids)
