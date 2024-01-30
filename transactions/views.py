from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse_lazy
from django.utils import timezone
from account.models import UserBankAccount
from django.shortcuts import get_object_or_404, redirect
from django.views import View
from django.http import HttpResponse
from django.views.generic import CreateView, ListView
from transactions.constants import DEPOSIT, WITHDRAW, LOAN, LOAN_PAID, BALANCE_TRANSFER
from datetime import datetime
from django.db.models import Sum
from transactions.forms import (
    DepositForm,
    WithdrawForm,
    LoanRequestForm,
    TransferForm
)
from transactions.models import Transaction


class TransactionCreateMixin(LoginRequiredMixin, CreateView):
    template_name = 'transactions/transaction_form.html'
    model = Transaction
    title = ''
    success_url = reverse_lazy('transaction_report')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs.update({
            'account': self.request.user.account
        })
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({
            'title': self.title
        })

        return context


class DepositMoneyView(TransactionCreateMixin):
    form_class = DepositForm
    title = 'Deposit'

    def get_initial(self):
        initial = {'transaction_type': DEPOSIT}
        return initial

    def form_valid(self, form):
        amount = form.cleaned_data.get('amount')
        account = self.request.user.account
        account.balance += amount
        account.save(
            update_fields=[
                'balance'
            ]
        )

        messages.success(
            self.request,
            f'{"{:,.2f}".format(float(amount))}$ was deposited to your account successfully'
        )

        return super().form_valid(form)


class WithdrawMoneyView(TransactionCreateMixin):
    form_class = WithdrawForm
    title = 'Withdraw Money'

    def get_initial(self):
        initial = {'transaction_type': WITHDRAW}
        return initial

    def form_valid(self, form):
        amount = form.cleaned_data.get('amount')
        account = self.request.user.account
        if hasattr(account, 'bankrupt') and not account.bankrupt:
            if account.balance >= amount:
                account.balance -= amount
                account.save(update_fields=['balance'])
                Transaction.objects.create(
                    account=account,
                    amount=amount,
                    balance_after_transaction=account.balance,
                    transaction_type=form.cleaned_data.get('transaction_type')
                )

                messages.success(
                    self.request,
                    f'{"{:,.2f}".format(float(amount))}$ was withdrawn from your account successfully'
                )
            else:
                messages.error(
                    self.request,
                    'Insufficient funds for the withdrawal.'
                )
        else:
            messages.error(
                self.request,
                'Sorry, the bank is bankrupt! Withdrawals are currently not allowed.'
            )

        return super().form_valid(form)


class LoanRequestView(TransactionCreateMixin):
    form_class = LoanRequestForm
    title = 'Request For Loan'

    def get_initial(self):
        initial = {'transaction_type': LOAN}
        return initial

    def form_valid(self, form):
        amount = form.cleaned_data.get('amount')
        current_loan_count = Transaction.objects.filter(
            account=self.request.user.account, transaction_type=3, loan_approve=True).count()
        if current_loan_count >= 3:
            return HttpResponse("You have cross the loan limits")
        messages.success(
            self.request,
            f'Loan request for {"{:,.2f}".format(float(amount))}$ submitted successfully'
        )

        return super().form_valid(form)


class TransactionReportView(LoginRequiredMixin, ListView):
    template_name = 'transactions/transaction_report.html'
    model = Transaction
    balance = 0

    def get_queryset(self):
        queryset = super().get_queryset().filter(
            account=self.request.user.account
        )
        start_date_str = self.request.GET.get('start_date')
        end_date_str = self.request.GET.get('end_date')

        if start_date_str and end_date_str:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()

            queryset = queryset.filter(
                timestamp__date__gte=start_date, timestamp__date__lte=end_date)
            self.balance = Transaction.objects.filter(
                timestamp__date__gte=start_date, timestamp__date__lte=end_date
            ).aggregate(Sum('amount'))['amount__sum']
        else:
            self.balance = self.request.user.account.balance

        return queryset.distinct()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({
            'account': self.request.user.account
        })

        return context

    def render_to_response(self, context, **response_kwargs):
        response = super().render_to_response(context, **response_kwargs)
        if hasattr(self, 'balance_after_transfer'):
            Transaction.objects.create(
                account=self.request.user.account,
                amount=self.balance_after_transfer,
                balance_after_transaction=self.balance,
                transaction_type=BALANCE_TRANSFER
            )

        return response

    def form_valid(self, form):
        response = super().form_valid(form)
        if self.balance != 0:
            self.balance_after_transfer = self.balance - form.instance.amount

        return response


class BalanceTransferView(LoginRequiredMixin, CreateView):
    model = Transaction
    template_name = 'transactions/transfer_amount.html'
    form_class = TransferForm
    title = 'Balance Transfer'
    success_url = reverse_lazy('transaction_report')

    def get_initial(self):
        initial = {'transaction_type': BALANCE_TRANSFER}
        return initial

    def form_valid(self, form):
        user_account = self.request.user.account
        transfer_to_account = form.cleaned_data['transfer_to_account']
        transfer_amount = form.cleaned_data['amount']

        try:
            to_account = UserBankAccount.objects.get(
                account_no=transfer_to_account)
        except UserBankAccount.DoesNotExist:
            messages.error(self.request, 'Destination account not found.')
            return self.form_invalid(form)

        if user_account.balance >= transfer_amount:
            user_account.balance -= transfer_amount
            user_account.save()
            to_account.balance += transfer_amount
            to_account.save()

            form.instance.account = user_account
            form.instance.transaction_type = BALANCE_TRANSFER
            form.instance.balance_after_transaction = user_account.balance
            form.save()

            messages.success(self.request, 'Transfer successful.')
            return super().form_valid(form)
        else:
            messages.error(
                self.request, 'Insufficient funds for the transfer.')
            return self.form_invalid(form)


class PayLoanView(LoginRequiredMixin, View):
    def get(self, request, loan_id):
        loan = get_object_or_404(Transaction, id=loan_id)
        print(loan)
        if loan.loan_approve:
            user_account = loan.account
            if loan.amount < user_account.balance:
                user_account.balance -= loan.amount
                loan.balance_after_transaction = user_account.balance
                user_account.save()
                loan.loan_approved = True
                loan.transaction_type = LOAN_PAID
                loan.save()
                return redirect('loan_list')
            else:
                messages.error(
                    self.request,
                    f'Loan amount is greater than available balance'
                )

        return redirect('loan_list')


class LoanListView(LoginRequiredMixin, ListView):
    model = Transaction
    template_name = 'transactions/loan_request.html'
    context_object_name = 'loans'

    def get_queryset(self):
        user_account = self.request.user.account
        queryset = Transaction.objects.filter(
            account=user_account, transaction_type=3)
        print(queryset)
        return queryset
