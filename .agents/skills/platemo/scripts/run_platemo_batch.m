function run_platemo_batch(config_path)
%RUN_PLATEMO_BATCH 按 JSON 配置顺序运行 PlatEMO 实验。
%   run_platemo_batch('experiment_config.json')
%
%   每个 算法 x 问题 x run 单独捕获错误。相同 run 编号会覆盖已有 .mat。
%   结束时打印 BATCH_SUMMARY；有失败则抛错，便于 matlab -batch 返回非零。
    if nargin < 1
        error('Usage: run_platemo_batch(config_path)');
    end
    config_path = resolvePath(char(config_path));
    if ~isfile(config_path)
        error('Config not found: %s', config_path);
    end

    script_dir = fileparts(mfilename('fullpath'));
    platemo_dir = findPlatEMO(script_dir);

    cfg = jsondecode(fileread(config_path));
    algorithms = asList(requiredField(cfg, 'algorithms'));
    problems = asList(requiredField(cfg, 'problems'));
    metrics = cellstr(requiredField(cfg, 'metrics'));
    N = double(requiredField(cfg, 'N'));
    maxFE = double(requiredField(cfg, 'maxFE'));
    runs = double(requiredField(cfg, 'runs'));
    saveCount = double(requiredField(cfg, 'save_count'));
    assert(N > 0 && maxFE > 0 && runs >= 1 && saveCount > 0, ...
        'N, maxFE, runs, and save_count must be positive (save_count > 0 writes Data/*.mat).');

    old_dir = cd(platemo_dir);
    log_path = fullfile(fileparts(config_path), 'batch_run.log');
    if isfile(log_path)
        delete(log_path);
    end
    diary(log_path);
    guard = onCleanup(@() restoreState(old_dir)); %#ok<NASGU>

    total = numel(algorithms) * numel(problems) * runs;
    count = 0;
    fail = 0;
    t0 = tic;
    fprintf('=== PlatEMO Batch Runner ===\n');
    fprintf('Config: %s\n', config_path);
    fprintf('Algorithms: %d | Problems: %d | Runs: %d | Total: %d\n', ...
        numel(algorithms), numel(problems), runs, total);
    fprintf('N=%g  maxFE=%g  save=%g  Metrics: %s\n', N, maxFE, saveCount, strjoin(metrics, ', '));
    fprintf('Results: %s\n\n', fullfile(platemo_dir, 'Data'));

    for a = 1:numel(algorithms)
        algoArg = callableArg(algorithms(a));
        algoName = char(algorithms(a).class);
        for p = 1:numel(problems)
            prob = problems(p);
            probArg = callableArg(prob);
            M = double(requiredField(prob, 'M'));
            for r = 1:runs
                count = count + 1;
                fprintf('[%d/%d] %s x %s (M=%g) run=%d ... ', ...
                    count, total, algoName, char(prob.class), M, r);
                try
                    args = {'algorithm', algoArg, 'problem', probArg, ...
                            'M', M, 'N', N, 'maxFE', maxFE, ...
                            'save', saveCount, 'metName', metrics, 'run', r};
                    if isfield(prob, 'D') && ~isempty(prob.D) && double(prob.D) > 0
                        args = [args, {'D', double(prob.D)}]; %#ok<AGROW>
                    end
                    platemo(args{:});
                    fprintf('OK\n');
                catch ME
                    if strcmp(ME.identifier, 'PlatEMO:Termination')
                        fprintf('OK\n');
                    else
                        fail = fail + 1;
                        fprintf('FAIL: %s\n', ME.message);
                    end
                end
            end
        end
    end

    elapsed = toc(t0);
    fprintf('\nBATCH_SUMMARY ok=%d fail=%d elapsed=%.0f\n', count - fail, fail, elapsed);
    if fail > 0
        error('PlatEMO:BatchFailed', '%d run(s) failed. See %s', fail, log_path);
    end
end

function value = requiredField(s, name)
    if ~isfield(s, name)
        error('Missing config field: %s', name);
    end
    value = s.(name);
end

function items = asList(items)
    % jsondecode 对单元素数组可能返回标量 struct，统一按结构体数组遍历。
    if iscell(items)
        items = [items{:}];
    end
end

function arg = callableArg(spec)
    name = char(requiredField(spec, 'class'));
    if isempty(regexp(name, '^[A-Za-z]\w*$', 'once'))
        error('Invalid class name: %s', name);
    end
    fh = str2func(name);
    if isfield(spec, 'params') && ~isempty(spec.params)
        vals = spec.params;
        if iscell(vals)
            extra = vals(:)';
        else
            extra = num2cell(double(vals(:)'));
        end
        arg = [{fh}, extra];
    else
        arg = fh;
    end
end

function platemo_dir = findPlatEMO(script_dir)
    % 技能目录、发行包根目录或 PlatEMO 目录本身都能启动。
    starts = {pwd, script_dir};
    env_root = getenv('PLATEMO_ROOT');
    if ~isempty(env_root)
        starts = [{env_root}, starts];
    end
    for i = 1:numel(starts)
        d = char(starts{i});
        for k = 1:8
            if isfile(fullfile(d, 'platemo.m'))
                platemo_dir = d;
                return;
            end
            nested = fullfile(d, 'PlatEMO', 'platemo.m');
            if isfile(nested)
                platemo_dir = fileparts(nested);
                return;
            end
            parent = fileparts(d);
            if isempty(parent) || strcmp(parent, d)
                break;
            end
            d = parent;
        end
    end
    error('platemo.m not found from %s or %s', pwd, script_dir);
end

function pathOut = resolvePath(pathIn)
    info = dir(pathIn);
    if isempty(info)
        pathOut = pathIn;
        return;
    end
    pathOut = fullfile(info(1).folder, info(1).name);
end

function restoreState(old_dir)
    diary off;
    cd(old_dir);
end
