# -*- coding: utf-8 -*-

import hashlib, string, random, os, shutil, time, datetime, math
from django.shortcuts import render_to_response, redirect
from django.utils.http import urlquote
from django.core.context_processors import csrf
from django.core.mail import send_mail
from django.core.paginator import Paginator, PageNotAnInteger, EmptyPage
from django.conf import settings
from django.contrib.auth import authenticate
from django.contrib import auth
from django.http import HttpResponse
from django.db import transaction
from django import forms
from app.models import People, Job, PeopleExtra, LockedStatus, ImportantPrompt
from app.forms import PeopleForm, LoginForm, PeopleNoPasswordForm, FindpwdForm ,\
    PeopleSearchForm, ImportantPromptForm
from app.forms import ChangepwdForm, AdminLoginForm, AdminChangePasswd, JobForm
from app.forms import AuditForm
from django.core.exceptions import ObjectDoesNotExist

degree_limit = {'1': u'硕士', '2': u'博士'}
lock_dict = {'1': u'master', '2': u'doctor'}

def auth_check(func):
    def wrapper(*args, **kwargs):
        request = args[0]
        if not request.session.has_key('profile'):
            return redirect('/login')
        request.session.set_expiry(3600)
        return func(*args, **kwargs)
    return wrapper

def home(request):
    peoples = People.objects.all()
    lock_status = {l.name: l for l in LockedStatus.objects.all()}
    try:
        ip = ImportantPrompt.objects.get(type=1)
    except Exception, e:
        ip = None
    return render_to_response("home.html", locals())

def howto(request):
    return render_to_response("help.html", locals())

def jobs(request, job_type_id=1):
    jobs = Job.objects.filter(degree_limit=degree_limit[job_type_id])
    lss = LockedStatus.objects.filter(name=lock_dict[job_type_id])
    ls = None if not lss else lss[0]
    return render_to_response("jobs.html", locals())

def applyjob(request, job_id):
    if request.session.has_key('profile'):
        return redirect("/")
    timestamp = time.time()
    locals().update(csrf(request))
    job = Job.objects.get(pk=job_id)
    job_one_type = ((x.pk, x) for x in Job.objects.filter(degree_limit=job.degree_limit))
    if request.method == 'POST':
        peopleForm = PeopleForm(request.POST)
        if peopleForm.is_valid():
            data = peopleForm.cleaned_data
            data['audit_step'] = 0
            data['query_password'] = hashlib.md5(data['query_password']).hexdigest()
            del data['query_password2']
            
            # 复制图片到相应目录
            avatar_path = "/".join(('static/upload/', peopleForm.cleaned_data["id_number"]))
            if not os.path.exists(avatar_path):
                os.mkdir(avatar_path)
            src_file = peopleForm.cleaned_data["avatar"][1:]
            dst_file = "/".join((avatar_path, os.path.basename(peopleForm.cleaned_data["avatar"])))
            if src_file!=dst_file:
                try:
                    shutil.move(src_file, dst_file)
                    peopleForm.cleaned_data["avatar"] = '/%s' % (dst_file, )
                except Exception:
                    pass
            
            people = People(**data)
            people.save()
            request.session['profile'] = people
            request.session.set_expiry(3600)
            message = u'信息提交成功<a href="/myinfo/">查看</a>已提交的信息'
            return render_to_response("msg.html", locals())
        else:
            peopleForm.fields['job'] = forms.ChoiceField(
                widget=forms.Select(), 
                choices=tuple([('', '---------')] + list(job_one_type)), 
                initial=job)
    else:
        peopleForm = PeopleForm(initial={'job': job_id})
        peopleForm.fields['job'] = forms.ChoiceField(
            widget=forms.Select(), 
            choices=tuple([('', '---------')] + list(job_one_type)), 
            initial=job)
    response = render_to_response("apply.html", locals())
    response['Pragma'] = 'no-cache'
    response['Cache-Control'] = 'no-cache must-revalidate proxy-revalidate'
    return response

@auth_check
def edit(request):
    profile = request.session['profile']
    if request.POST.get('id_number')==profile.id_number:
        peopleForm = PeopleNoPasswordForm(instance=profile)
        peopleForm.fields['id_number'].widget.attrs['readonly'] = True
        # 限制岗位为某一类型（硕士或者博士）
        job = Job.objects.get(pk=profile.job_id)
        job_one_type = ((x.pk, x) for x in Job.objects.filter(degree_limit=job.degree_limit))
        peopleForm.fields['job'] = forms.ChoiceField(
            widget=forms.Select(), 
            choices=tuple([('', '---------')] + list(job_one_type)), 
            initial=job)
        locals().update(csrf(request), operate='edit')
        return render_to_response("apply.html", locals())
    else:
        return redirect('/myinfo/')

@auth_check
def update(request):
    locals().update(csrf(request), operate='edit')
    if request.method == 'POST':
        peopleForm = PeopleNoPasswordForm(request.POST)
        if (request.POST.get('id_number') == request.session['profile'].id_number and 
            peopleForm.is_valid()):
            data = peopleForm.cleaned_data
            data['audit_step'] = 0
            # 把不需要更新的字段去掉
            del data['id_number'], data['query_password']
            people = People.objects.get(pk=request.session['profile'].id)
            for k, v in data.items():
                setattr(people, k, v)
            people.save()
            try:
                people.peopleextra.delete()
            except Exception:
                pass
            # 更新session
            request.session['profile'] = people
            message = u'信息修改成功。<a href="/myinfo">查看</a>'
            return render_to_response("msg.html", locals())
        return render_to_response("apply.html", locals())
    else:
        return redirect('/')

@auth_check
def myinfo(request):
    locals().update(csrf(request))
    people = People.objects.get(pk=request.session['profile'].id)
    return render_to_response("myinfo.html", locals())

@auth_check
def progress(request):
    locals().update(csrf(request))
    people = People.objects.get(pk=request.session['profile'].id)
    can_print_ticket = True and people.job.degree_limit==u'硕士'
    lss = LockedStatus.objects.filter(name='print')
    is_lock = True and lss and lss[0].is_lock
    pes = PeopleExtra.objects.filter(people=people)
    if (os.path.exists('run/ticket_assigned.lock') and 
        pes and pes[0].ticket_number):
        assign_end = True
    else:
        assign_end = False
    can_print = is_lock and (assign_end or people.job.degree_limit==u'博士')
    if people.job.degree_limit==u'博士':
        can_print_ticket = False
        assign_end = True
        can_print = True
    lock_status = {l.name: l for l in LockedStatus.objects.all()}
    return render_to_response("progress.html", locals())

@auth_check
def printinfo(request, ptype):
    people = People.objects.get(pk=request.session['profile'].id)
    if ptype == 'audit':
        return render_to_response("audit_table.html", locals())
    else:
        return render_to_response("ticket_table.html", locals())

def login(request):
    locals().update(csrf(request))
    if request.method == 'POST':
        loginForm = LoginForm(request.POST)
        if loginForm.is_valid():
            people = People.objects.filter(
                id_number=loginForm.cleaned_data['id_number'], 
                query_password=hashlib.md5(loginForm.cleaned_data['password']).hexdigest()
            )
            if people:
                request.session['profile'] = people[0]
                request.session.set_expiry(3600)
                return redirect('/progress/')
    else:
        loginForm = LoginForm()
    return render_to_response('login.html', locals())

def logout(request):
    if request.session.has_key('profile'):
        del request.session['profile']
    return redirect('/')

def findpwd(request):
    locals().update(csrf(request))
    if request.method == 'POST':
        form = FindpwdForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            people = People.objects.filter(id_number=data['id_number'], email=data['email'])
            if people:
                pwd = ''.join(random.choice(string.letters + string.digits) for x in range(12))
                pwdhash = hashlib.md5(pwd).hexdigest()
                subject = (u'找回%s在内蒙古工业大学申请的 %s(%s) 的查询密码' % 
                           (people[0].name, people[0].job.major, people[0].job.job_type))
                msg = ((u"亲爱的%s\n\n您的查询密码已经被系统重置，请使用下面的密码登录\n\n"
                        u"%s\n\nhttp://localhost:8000/login") % 
                       (people[0].name, pwd))
                is_sent = send_mail(subject, msg, settings.ADMIN_EMAIL, [people[0].email])
                if is_sent:
                    people[0].query_password = pwdhash
                    people[0].save()
                    message = u'您的密码已经发送到您的邮箱，请登录您的邮箱查看'
                else:
                    message = u'邮件发送失败，请联系内蒙古工业大学人事处00000-0000000'
                return render_to_response("msg.html", locals())
            else:
                form.errors['__all__'] = form.error_class([u'未能匹配身份证号与电子邮箱'])
    else:
        form = FindpwdForm()
    return render_to_response("findpwd.html", locals())

@auth_check
def changepwd(request):
    locals().update(csrf(request))
    if request.method == 'POST':
        form = ChangepwdForm(request.POST)
        if form.is_valid():
            old_query_password = hashlib.md5(form.cleaned_data['old_password']).hexdigest()
            people = People.objects.filter(pk=request.session['profile'].id, 
                                           query_password=old_query_password)
            if people:
                query_password = hashlib.md5(form.cleaned_data['new_password']).hexdigest()
                people[0].query_password = query_password
                people[0].save()
                message = u'密码修改成功'
                return render_to_response("msg.html", locals())
            else:
                form.errors['old_password'] = form.error_class([u'原始密码不匹配'])
    else:
        form = ChangepwdForm()
    return render_to_response("changepwd.html", locals()) 

def protocol(request, type_id):
    return render_to_response("protocol.html", locals())

def uploadimage(request):
    filename = request.FILES['avatar'].name
    filedata = request.FILES['avatar']
    prefix, suffix = os.path.splitext(filename)
    if filedata.file:
        filename = (
            "static/upload/tmp/%s%s" % 
            (hashlib.md5(str(time.time())).hexdigest(),
             "%s%s" % (hashlib.md5(str(time.time())).hexdigest(), suffix)))
        open(filename, "wb").write(filedata.read())
    for root, dirs, files in os.walk("static/upload/tmp/"):
        for filespath in files:
            tmpfilename = "%s/%s" % (root, filespath)
            if time.time() - os.stat(tmpfilename).st_mtime > 86400:
                os.unlink(tmpfilename)
    return HttpResponse("/%s" % filename)


# ---------- admin views ----------


def m_auth_check(func):
    def wrapper(*args, **kwargs):
        request = args[0]
        if not request.user.is_authenticated():
            return redirect('/management/login/')
        return func(*args, **kwargs)
    return wrapper

@m_auth_check
def m_people_del(request):
    if request.method == 'POST' and request.POST.get('operate') == 'del':
        people_ids = request.POST.getlist('people_id')
        peoples = People.objects.filter(pk__in=people_ids)
        peoples.delete()
        request.session['message'] = u'删除成功'
        return redirect(request.META['HTTP_REFERER'])

@m_auth_check
def m_audit(request, people_id=0):
    locals().update(csrf(request))
    if request.method == 'POST':
        people = People.objects.get(pk=request.POST.get('people'))
        form = AuditForm(request.POST)
        if form.is_valid():
            db_time = datetime.datetime(*people.last_edit_at.timetuple()[:6])
            ori_time = datetime.datetime.utcfromtimestamp(float(request.POST.get('last_edit_at')))
            if int((db_time - ori_time).total_seconds()) is not 0:
                message = u'%s 的状态已经被其他管理员修改' % (people.name, )
                return render_to_response("m_audit.html", locals())
            try:
                people.peopleextra.audit_step = form.cleaned_data['audit_step']
                if form.cleaned_data.has_key('reason'):
                    people.peopleextra.reason = form.cleaned_data['reason']
                people.peopleextra.save()
            except ObjectDoesNotExist:
                form.save()
            people.audit_step = form.cleaned_data['audit_step']
            people.save()
            request.session['message'] = u'%s的审核状态保存成功' % (people.name, )
            
            status_dict = {0: 'elementary', 1: 'passed', 7: 'notpass', 8: 'unqualified'}
            return redirect('/management/plist/%s/' % (status_dict[int(form.cleaned_data['audit_step'])],))
    else:
        people = People.objects.get(pk=people_id)
        initail = {'audit_step': people.audit_step}
        try:
            reason = people.peopleextra.reason
            initail.update(reason=reason)
        except ObjectDoesNotExist:
            pass
        form = AuditForm(initial=initail)
    return render_to_response("m_audit.html", locals())

@m_auth_check
def m_people_list(request, status, page=1):
    locals().update(csrf(request))
    status_dict = {
        'elementary': {'filter': {'audit_step__lt': 1}, 'tpl': 'm_elementary.html'}, 
        'passed': {'filter': {'audit_step': 1}, 'tpl': 'm_passed.html'}, 
        'notpass': {'filter': {'audit_step': 7}, 'tpl': 'm_notpass.html'},
        'unqualified': {'filter': {'audit_step': 8}, 'tpl': 'm_unqualified.html'}, 
        'search':  {'filter': {}, 'tpl': 'm_people_list.html'}
    }
    if not status_dict.has_key(status):
        return redirect("/management")
    params = status_dict[status]['filter']
    all_people = None
    if request.method == 'POST':
        psForm = PeopleSearchForm(request.POST)
        psForm.is_valid()
        if psForm.cleaned_data:
            if psForm.cleaned_data['id_number']:
                params.update(id_number__contains=psForm.cleaned_data['id_number'])
            if psForm.cleaned_data['name']:
                params.update(name__contains=psForm.cleaned_data['name'])
            if psForm.cleaned_data.has_key('gender'):
                params.update(gender=psForm.cleaned_data['gender'])
            if psForm.cleaned_data['major']:
                params.update(job__major__contains=psForm.cleaned_data['major'])
            if psForm.cleaned_data['department']:
                params.update(job__department__contains=psForm.cleaned_data['department'])
            all_people = People.objects.filter(**params).order_by('-last_edit_at')
    else:
        psForm = PeopleSearchForm()
        if params:
            all_people = People.objects.filter(**params).order_by('-last_edit_at')
    if all_people:
        paginator = Paginator(all_people, 30)
        try:
            peoples = paginator.page(page)
        except PageNotAnInteger:
            peoples = paginator.page(1)
        except EmptyPage:
            peoples = paginator.page(paginator.num_pages)
    if request.session.has_key('message'):
        message = request.session['message']
        del request.session['message']
    menu_active = status
    return render_to_response(status_dict[status]['tpl'], locals())

@m_auth_check
def m_people(request, people_id):
    people = People.objects.get(pk=people_id)
    return render_to_response('m_people.html', locals())

@m_auth_check
def m_ticket(request):
    message = None
    lines = []
    chineseExtra = list(PeopleExtra.objects.filter(
            people__test_paper_language=u'汉文', audit_step=1, 
            people__job__degree_limit=u'硕士').order_by("people__job"))
    mongolianExtra = list(PeopleExtra.objects.filter(
            people__test_paper_language=u'蒙文', audit_step=1, 
            people__job__degree_limit=u'硕士').order_by("people__job"))
    chinese_rest_count = len(chineseExtra)%30
    mongolian_rest_count = len(mongolianExtra)%30
    
    pes = []
    if chinese_rest_count+mongolian_rest_count <= 30:
        pes += chineseExtra[:len(chineseExtra)-chinese_rest_count]
        pes += mongolianExtra[:len(mongolianExtra)-mongolian_rest_count]
        pes += chineseExtra[len(chineseExtra[:len(chineseExtra)-chinese_rest_count]):]
        pes += mongolianExtra[len(mongolianExtra[:len(mongolianExtra)-mongolian_rest_count]):]
        diff = False
    else:
        pes = chineseExtra+mongolianExtra
        diff = True
    
    last_lang = None
    room, seat, seat_in_room = 1, 1, 30
    for index in range(len(pes)):
        lang = pes[index].people.test_paper_language
        if last_lang == None:
            last_lang = lang
        if last_lang != lang and diff:
            room += 1
            seat = 1
        last_lang = lang
        people_room = '%02d' % room
        people_seat = '%02d' % seat
        ticket = '%d%s%s' % (datetime.date.today().year, people_room, people_seat)
        pes[index].ticket_number = ticket
        pes[index].exam_room = people_room
        pes[index].seat = people_seat
        
        seat += 1
        
        if seat > seat_in_room:
            room += 1
            seat = 1
    
    langpe = None
    try:
        for pe in pes:
            langpe = pe
            pe.save()
    except:
        lines.append(u'%s:0' % langpe.people.test_paper_language)
        message = u'<font color="red">分配准考证失败，请重试</font>'
    else:
        lines.append(u'%s:1' % langpe.people.test_paper_language)

    if not message:
        message = (u'准考证号分配完毕。<br>总共%s个考场' % (room, ))
        if not diff:
            message += (u'，第%d考场为混合考场，汉文：%d，蒙文：%d' % 
                        (room, chinese_rest_count, mongolian_rest_count))
        else:
            message += u'，没有混合考场'
    fp = open('run/ticket_assigned.lock', 'w')
    fp.write((u"\n".join(lines)).encode('utf-8'))
    fp.close()
    request.session['message'] = message
    return redirect("/management/stat/")

@m_auth_check
def m_stat(request):
    locals().update(csrf(request))
    jobs = Job.objects.all().order_by('-degree_limit')
    for (i, job) in enumerate(jobs):
        count_apply = People.objects.filter(audit_step=1, job=jobs[i].id).count()
        jobs[i].count_apply = count_apply
        if count_apply:
            denominator = float(job.count) if job.count else 1.0
            rate = count_apply/denominator
            jobs[i].rate = "1:%d" % rate
            if rate > 3:
                jobs[i].is_exam_open = u'是'
            else:
                jobs[i].is_exam_open = u'否'
        else:
            jobs[i].rate = "1:0"
            jobs[i].is_exam_open = u'否'
    # 统计中文跟蒙文试卷人数
    test_paper = {'han': People.objects.filter(
                        test_paper_language=u'汉文', audit_step=1, 
                        job__degree_limit=u'硕士').count(), 
                  'meng': People.objects.filter(
                        test_paper_language=u'蒙文', audit_step=1, 
                        job__degree_limit=u'硕士').count()}
    if request.session.has_key('message'):
        message = request.session['message']
        del request.session['message']
    ticket_assigned = []
    assign_failed, failed_lang = False, ''
    if os.path.exists('run/ticket_assigned.lock'):
        ticket_assigned = [l.strip().split(':') for l in open('run/ticket_assigned.lock').readlines()]
        for ta in ticket_assigned:
            if len(ta) == 2 and int(ta[1]) == 0:
                assign_failed = True
                failed_lang = ta[0]
    menu_active = 'stat'
    
    room_num = math.ceil((test_paper['han']+test_paper['meng'])/30.0)
    if test_paper['han']%30+test_paper['meng']%30 <= 30:
        mixed_exam_msg = (u'总共有%d个考场，第%d考场为混合考场，汉文：%d，蒙文：%d' % 
                          (room_num, room_num, test_paper['han']%30, test_paper['meng']%30))
    else:
        mixed_exam_msg = u'总共有%d个考场，没有混合考场' % room_num
    
    return render_to_response('m_stat.html', locals())

@m_auth_check
def m_lock(request):
    menu_active = 'lock'
    locals().update(csrf(request))
    if (request.method == 'POST' and 
        request.POST.get('lock_name') in ('doctor', 'master', 'print')):
        ls = LockedStatus.objects.filter(name=request.POST.get('lock_name'))
        if not ls:
            ls = LockedStatus(name=request.POST.get('lock_name'), is_lock=True)
        else:
            ls = ls[0]
            ls.is_lock = not ls.is_lock
        ls.save()
        return redirect("/management/lock/")
    lock_status = {l.name: l for l in LockedStatus.objects.all()}
    return render_to_response('m_lock.html', locals())

@m_auth_check
def m_export(request, etype=None):
    params = {}
    if 'passed' == etype:
        params.update(audit_step=1)
        peoples = People.objects.filter(**params).order_by('job__degree_limit')
        
        response = HttpResponse(mimetype="application/ms-excel")
        response['Content-Disposition'] = u'attachment; filename="%s.xls"' % urlquote(u'通过审核名单')

        import xlwt
        excel = xlwt.Workbook(encoding='unicode')
        table = excel.add_sheet(u'全部')

        table_header = [
            u'序号', u'岗位类型', u'招聘部门', u'专业要求', u'学历要求', u'姓名', u'性别', 
            u'民族', u'出生日期', u'身份证号', u'政治面貌', u'婚姻状况', u'是否蒙汉兼通', 
            u'是否服务基层人员', u'籍贯', u'户口所在地', u'电子邮件', u'手机号', 
            u'其他联系方式', u'外语及水平', u'参加工作时间', u'专业技术资格', 
            u'执业资格', u'其他资格', u'第一学历名称', u'第一学位', u'第一学历毕业院校', 
            u'第一学历所学专业', u'第一学历开始时间', u'第一学历结束时间', u'最高学历名称', 
            u'最高学位', u'最高学历毕业院校', u'最高学历所学专业', u'最高学历开始时间', 
            u'最高学历结束时间', u'其他学习经历一开始时间', u'其他学习经历一结束时间', 
            u'其他学习经历一学习形式', u'其他学习经历一学历', u'其他学习经历一学位', 
            u'其他学习经历一学习所学专业', u'其他学习经历一学习单位', u'其他学习经历二开始时间', 
            u'其他学习经历二结束时间', u'其他学习经历二学习形式', u'其他学习经历二学历', 
            u'其他学习经历二学位', u'其他学习经历二学习所学专业', u'其他学习经历二学习单位', 
            u'获奖情况、学术成果及个人特长']
        for (column, v) in enumerate(table_header):
            table.write(0, column, v)
        for (i, p) in enumerate(peoples):
            line = [i+1, p.job.job_type, p.job.department, p.job.major, p.job.degree_limit, 
                    p.name, p.gender, p.nation, p.birthday, p.id_number, p.political_status, 
                    p.marital_status, p.is_han_mongolia_both, p.is_basic_attendant, 
                    p.hometown_prov+u'-'+p.hometown_city, p.residence_prov+u'-'+p.residence_city, 
                    p.email, (u"'%s" % p.phone), p.other_contact, p.foreign_language_level, 
                    (u"%d/%d" % (p.start_work_year, p.start_work_month)), p.technical_qualification, 
                    p.operation_qualification, p.other_qualification, p.first_edu_bkgrd, p.first_edu_degree, 
                    p.first_edu_university, p.first_edu_major, (u"%d/%d" % (p.first_edu_start_year, p.first_edu_start_month)), 
                    (u"%d/%d" % (p.first_edu_end_year, p.first_edu_end_month)), p.high_edu_bkgrd, p.high_edu_degree, 
                    p.high_edu_university, p.high_edu_major, (u"%d/%d" % (p.high_edu_start_year, p.high_edu_start_month)), 
                    (u"%d/%d" % (p.high_edu_edu_year, p.high_edu_edu_month)), 
                    (u"%s/%s" % (p.other_edu_start_year, p.other_edu_start_month) if p.other_edu_start_year else u''), 
                    (u"%s/%s" % (p.other_edu_edu_year, p.other_edu_edu_month) if p.other_edu_edu_year else u''), 
                    p.other_edu_type, p.other_edu_bkgrd, 
                    p.other_edu_degree, p.other_edu_major, p.other_edu_unit, 
                    (u"%s/%s" % (p.other_edu_start_year_2, p.other_edu_start_month_2) if p.other_edu_start_year_2 else u''), 
                    (u"%s/%s" % (p.other_edu_edu_year_2, p.other_edu_edu_month_2) if p.other_edu_edu_year_2 else u''), 
                    p.other_edu_type_2, p.other_edu_bkgrd_2, 
                    p.other_edu_degree_2, p.other_edu_major_2, p.other_edu_unit_2, p.special_skill]

            for (column, v) in enumerate(line):
                table.write(i+1, column, v)
        excel.save(response)
        return response
    menu_active = 'export'
    return render_to_response('m_export.html', locals())

@m_auth_check
def m_admin(request):
    return render_to_response("m_admin.html", locals())

@m_auth_check
def m_job(request):
    '''岗位列表'''
    locals().update(csrf(request))
    jobs = Job.objects.all()
    if request.session.has_key('message'):
        message = request.session['message']
        del request.session['message']
    menu_active = 'job'
    return render_to_response("m_job_list.html", locals())

@m_auth_check
def m_job_add(request):
    locals().update(csrf(request))
    if request.method == 'POST':
        form = JobForm(request.POST)
        if form.is_valid():
            if request.POST.get('edit') == '1':
                job = Job.objects.get(pk=int(request.POST.get('job_id')))
                for k, v in form.cleaned_data.items():
                    setattr(job, k, v)
                job.save()
                request.session['message'] = u'岗位信息修改成功'
            else:
                form.save()
                request.session['message'] = u'岗位信息添加成功'
            return redirect("/management/job/")
    else:
        form = JobForm()
    menu_active = 'job'
    return render_to_response("m_job_add.html", locals())

@m_auth_check
def m_job_del(request, job_id):
    job = Job.objects.get(pk=job_id)
    job.delete()
    request.session['message'] = u'%s - %s删除成功' % (job.major, job.job_type)
    return redirect("/management/job/")

@m_auth_check
def m_job_edit(request, job_id):
    locals().update(csrf(request))
    job = Job.objects.get(pk=job_id)
    form = JobForm(instance=job)
    edit = True
    menu_active = 'job'
    return render_to_response("m_job_add.html", locals())

@m_auth_check
def m_prompt(request, type_id=1):
    menu_active = 'prompt'
    locals().update(csrf(request))
    ips = ImportantPrompt.objects.filter(type=type_id)
    if request.method == 'POST':
        form = ImportantPromptForm(request.POST)
        if form.is_valid():
            if request.POST.get('type'):
                ip = ImportantPrompt.objects.get(type=request.POST.get('type'))
                ip.content = form.cleaned_data['content']
                ip.save()
            else:
                ip = ImportantPrompt(type=type_id, content=form.cleaned_data['content'])
                ip.save()
        return redirect("/management/prompt/%s" % type_id)
    else:
        if ips:
            form = ImportantPromptForm(initial={'type': ips[0].type, 'content': ips[0].content})
        else:
            form = ImportantPromptForm()
    return render_to_response("m_prompt.html", locals())

def m_change_passwd(request):
    locals().update(csrf(request))
    if request.method == 'POST':
        form = AdminChangePasswd(request.POST)
        if form.is_valid() and request.user.check_password(request.POST.get('old_passwd')):
            request.user.set_password(request.POST.get('new_passwd'))
            request.user.save()
            message = u'密码修改成功'
            return render_to_response("m_msg.html", locals())
    else:
        form = AdminChangePasswd()
    menu_active = 'change_passwd'
    return render_to_response("m_passwd.html", locals())

def m_login(request):
    locals().update(csrf(request))
    if request.method == 'POST':
        form = AdminLoginForm(request.POST)
        if form.is_valid():
            user = authenticate(username=request.POST.get('username'), 
                                password=request.POST.get('password'))
            if user and user.is_active:
                auth.login(request, user)
                return redirect("/management/")
    else:
        form = AdminLoginForm()
    return render_to_response("m_login.html", locals())

def m_logout(request):
    auth.logout(request)
    return redirect("/management/login/")



#def test(request):
#    people = People.objects.get(id=1)
#    peopleExtra = PeopleExtra.objects.filter(people=people)[0]
#    
#    old_pid = people.id
#    people.pk = None
##    people.test_paper_language = u'汉文'
#    people.save()
#    
#    old_pe_id = peopleExtra.id
#    peopleExtra.pk = None
#    peopleExtra.people_id = people.id
#    peopleExtra.save()
#    
#    max_id = People.objects.all().order_by("-id")[0]
#
#    return render_to_response("test.html", locals())
#
#def testshow(request):
##    pp = People.objects.all()[2:]
##    for xx in pp:
##        xx.delete()
##    pepe = PeopleExtra.objects.all()[2:]
##    for xexe in pepe:
##        xexe.delete()
#    
#    people = People.objects.filter(
#            audit_step=1, 
#            job__degree_limit=u'硕士').order_by('peopleextra__ticket_number')
#    peopleExtra = PeopleExtra.objects.all()
#    
#    
#    return render_to_response("testshow.html", locals())
